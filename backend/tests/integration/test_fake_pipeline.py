"""M3 완료 조건: 가짜 클라이언트만으로 수집 → 관찰 → 해석 → 매칭 → 집계 → 결과 JSON까지 이어진다.

M4의 핸들러가 할 조합을 여기서 최소한으로 흉내 낸다. 실제 유료 API는 부르지 않는다.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.rules.aggregation import aggregate_places, job_status
from shared.rules.matching import match_candidate
from shared.rules.ranking import rank_places
from shared.schemas.common import Category
from shared.schemas.interpretation import InterpretationResult
from shared.schemas.items import PlaceEvidenceItem, VideoRef
from shared.schemas.observation import ObservationResult
from shared.schemas.places import GeoPoint, PlaceHit
from shared.schemas.result import JobResult, ResultPlace
from shared.schemas.youtube import VideoMeta
from tests.fakes import FakeBedrock, FakeGemini, FakePlaces, FakeYouTube

CONTRACTS = Path(__file__).parent.parent / "fixtures" / "contracts"
VERSION = "v1-haiku45"
OSAKA = GeoPoint(lat=34.69, lng=135.50)
V1, V2, V3 = "dQw4w9WgXcQ", "vlog2xxxxxx", "vlog3xxxxxx"


def _meta(vid: str, channel: str, minutes: int) -> VideoMeta:
    return VideoMeta(
        video_id=vid,
        channel_id=channel,
        title="오사카 브이로그",
        description="",
        duration_sec=minutes * 60,
        privacy_status="public",
        published_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


def _load(name: str) -> str:
    return (CONTRACTS / name).read_text(encoding="utf-8")


def _second_video() -> tuple[ObservationResult, InterpretationResult]:
    obs = ObservationResult.model_validate(
        {
            "video_id": V2,
            "clues": [
                {
                    "start_sec": 300,
                    "end_sec": 420,
                    "clue_type": "SPEECH",
                    "heard_name": "이치란",
                    "utterance": "오픈 직후라 줄 거의 없었어요. 맛있다!",
                },
            ],
        }
    )
    interp = InterpretationResult.model_validate(
        {
            "video_id": V2,
            "analysis_version": VERSION,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "names": ["이치란"],
                    "branch_hint": "도톤보리",
                    "search_queries": ["이치란 도톤보리"],
                    "category": "RESTAURANT",
                    "visit_status": "VISITED",
                    "clue_refs": [0],
                    "ratings": {"overall": "POSITIVE", "taste": "POSITIVE", "wait": "POSITIVE"},
                    "time_evidence": [
                        {
                            "kind": "WAIT_EXPERIENCE",
                            "situation": "OPENING",
                            "evidence_text": "오픈 직후라 줄 거의 없었어요",
                        }
                    ],
                },
            ],
        }
    )
    return obs, interp


def test_pipeline_runs_end_to_end_on_fakes() -> None:
    youtube = FakeYouTube(
        {"오사카 브이로그": [V1, V2, V3]},
        [_meta(V1, "ch1", 15), _meta(V2, "ch2", 22), _meta(V3, "ch3", 18)],
    )
    obs1 = ObservationResult.model_validate_json(_load("observation/valid_osaka.json"))
    int1 = InterpretationResult.model_validate_json(_load("interpretation/valid_osaka.json"))
    obs2, int2 = _second_video()
    gemini = FakeGemini({V1: obs1, V2: obs2})  # V3는 관찰 실패
    bedrock = FakeBedrock({V1: int1, V2: int2})
    dotonbori = PlaceHit(
        place_id="ChIJ_ichiran",
        name="이치란 도톤보리점",
        address="오사카시 주오구 도톤보리 1-4",
        location=GeoPoint(lat=34.6687, lng=135.5013),
    )
    places = FakePlaces(
        {"一蘭 道頓堀店": [dotonbori], "이치란 도톤보리": [dotonbori]}, cities={"오사카": OSAKA}
    )

    # collect
    ids = youtube.search(
        "오사카 브이로그", order="relevance", published_after=datetime(2024, 10, 15, tzinfo=UTC)
    )
    refs = [
        VideoRef(video_id=m.video_id, channel_id=m.channel_id, analysis_version=VERSION)
        for m in youtube.videos(ids)
        if m.duration_sec >= 180
    ]

    # observe → interpret → match (영상별, 실패해도 다른 영상은 계속)
    bias = places.locate("오사카")
    evidences: list[PlaceEvidenceItem] = []
    categories: dict[str, Category] = {}
    done: list[VideoRef] = []
    for ref in refs:
        try:
            observation = gemini.observe(ref.video_id).result
        except Exception:
            done.append(ref.model_copy(update={"state": "FAILED"}))
            continue
        interpretation = bedrock.interpret(observation, VERSION).result
        for cand in interpretation.candidates:
            hits = places.search_candidate(cand.search_queries, bias=bias)
            outcome = match_candidate(cand.names, cand.branch_hint, hits)
            if outcome.place_id is None:
                continue
            clue = observation.clues[cand.clue_refs[0]]
            start = clue.start_sec
            categories[outcome.place_id] = cand.category
            evidences.append(
                PlaceEvidenceItem(
                    place_id=outcome.place_id,
                    sk=PlaceEvidenceItem.make_sk(ref.channel_id, ref.video_id, VERSION, start),
                    video_id=ref.video_id,
                    channel_id=ref.channel_id,
                    analysis_version=VERSION,
                    evidence_key=PlaceEvidenceItem.make_evidence_key(
                        outcome.place_id, VERSION, start
                    ),
                    visit_status=cand.visit_status,
                    match_status="CONFIRMED",
                    video_time_range={"start_sec": start, "end_sec": clue.end_sec},
                    ratings=cand.ratings,
                    evidence_text=clue.utterance or clue.seen_text or "",
                    visit_time_evidence=cand.time_evidence,
                )
            )
        done.append(ref.model_copy(update={"state": "DONE"}))

    # aggregate → rank → result JSON
    aggregates = aggregate_places(evidences, done)
    ranked = {r.place_id: r.rank for r in rank_places(aggregates, categories=categories)}
    result = JobResult(
        job_id="job-1",
        destination="오사카",
        analyzed_channels=sum(r.state == "DONE" for r in done),
        failed_videos=sum(r.state == "FAILED" for r in done),
        places=[
            ResultPlace(
                place_id=a.place_id,
                name="이치란 · 도톤보리",
                category=categories[a.place_id],
                lat=34.6687,
                lng=135.5013,
                rank=ranked[a.place_id],
                match_status="CONFIRMED",
                channels={"visited": a.channels_visited, "denominator": a.denominator},
                ratings=a.ratings,
                time_evidence=a.time_evidence,
                evidence=[
                    {
                        "channel_id": e.channel_id,
                        "video_id": e.video_id,
                        "start_sec": e.video_time_range.start_sec,
                        "text": e.evidence_text,
                    }
                    for e in a.evidence
                ],
            )
            for a in aggregates
            if a.place_id in ranked
        ],
    )

    body = json.loads(result.model_dump_json())
    assert job_status(done) == "PARTIAL"
    assert (body["analyzedChannels"], body["failedVideos"]) == (2, 1)
    [ichiran] = body["places"]
    assert ichiran["placeId"] == "ChIJ_ichiran"
    assert ichiran["channels"] == {"visited": 2, "denominator": 2}
    assert ichiran["ratings"]["taste"]["positive"] == 2
    assert ichiran["rank"] == 1
    # 도톤보리 강변 후보는 Places 결과가 없어 버려짐
    assert len(body["places"]) == 1
    # 호출 횟수: Gemini 영상당 1회, Places 예산 안
    assert gemini.calls == {V1: 1, V2: 1, V3: 1}
    assert bedrock.calls == {V1: 1, V2: 1}
    assert places.calls <= 1 + 2 * 3

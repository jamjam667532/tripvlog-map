"""aggregate 핸들러: 대체 영상 연결, 채널 단위 집계·순위·지역 묶음, 결과 JSON."""

import json
from typing import Any

from functions.aggregate.handler import Deps, run
from shared.repos import Repos, analysis_key, result_key, with_refs
from shared.schemas.events import AggregateInput, AggregateOutput, ReplaceOutput
from shared.schemas.items import JobItem, PlaceItem, SpareVideo, VideoRef
from shared.schemas.match import ConfirmedMatch, MatchSummary, UnconfirmedMatch
from shared.schemas.places import GeoPoint
from shared.settings import Settings
from tests.integration.factories import NOW, NOW_EPOCH, VERSION, guest_job
from tests.unit.rules.factories import evidence


def _job(repos: Repos, refs: list[VideoRef], spares: list[SpareVideo] | None = None) -> JobItem:
    job = guest_job()
    repos.jobs.create(job)
    return repos.jobs.mutate(
        str(job.job_id),
        lambda j: with_refs(j, refs).model_copy(update={"spare_videos": spares or []}),
        NOW,
    )


def ref(video: str, channel: str, state: str = "DONE", **kw: Any) -> VideoRef:
    return VideoRef.model_validate(
        {"videoId": video, "channelId": channel, "analysisVersion": VERSION, "state": state, **kw}
    )


def _deps(repos: Repos, settings: Settings) -> Deps:
    return Deps(settings=settings, repos=repos, clock=lambda: NOW)


def _aggregate(repos: Repos, settings: Settings, job: JobItem) -> AggregateOutput:
    out = run(AggregateInput(job_id=job.job_id), _deps(repos, settings))
    assert isinstance(out, AggregateOutput)
    return out


def _replace(repos: Repos, settings: Settings, job: JobItem) -> ReplaceOutput:
    out = run(AggregateInput(job_id=job.job_id, action="replace"), _deps(repos, settings))
    assert isinstance(out, ReplaceOutput)
    return out


def _place(repos: Repos, place_id: str, name: str, category: str, lat: float, lng: float) -> None:
    repos.places.put_place_if_absent(
        PlaceItem.model_validate(
            {
                "placeId": place_id,
                "destination": "오사카",
                "extractedName": name,
                "categoryFromVideo": category,
            }
        )
    )
    repos.coords.put(place_id, GeoPoint(lat=lat, lng=lng), now=NOW_EPOCH, ttl_days=25)


def _summary(repos: Repos, video: str, **kw: Any) -> None:
    repos.blobs.put_model(
        analysis_key(video, VERSION, "match"),
        MatchSummary(video_id=video, analysis_version=VERSION, **kw),
    )


def test_aggregate_builds_ranked_result(
    repos: Repos, settings: Settings, aws: tuple[Any, Any]
) -> None:
    job = _job(repos, [ref("v1", "c1"), ref("v2", "c2"), ref("v3", "c3", "FAILED")])
    _place(repos, "P_ichiran", "이치란", "RESTAURANT", 34.6687, 135.5013)
    _place(repos, "P_cafe", "카페", "CAFE", 34.6690, 135.5020)
    _place(repos, "P_castle", "오사카성", "ATTRACTION", 34.6873, 135.5262)
    _place(repos, "P_expired", "만료", "RESTAURANT", 34.70, 135.49)
    repos.coords.put("P_expired", GeoPoint(lat=34.7, lng=135.49), now=0, ttl_days=1)
    taste = {"overall": "POSITIVE", "taste": "POSITIVE"}
    for item in [
        evidence("P_ichiran", "c1", "v1", 750, ratings=taste),
        evidence("P_ichiran", "c1", "v1", 900, ratings={"wait": "NEGATIVE"}),
        evidence(
            "P_ichiran",
            "c2",
            "v2",
            300,
            ratings={"wait": "POSITIVE"},
            time=[{"kind": "WAIT_EXPERIENCE", "situation": "OPENING"}],
        ),
        evidence("P_cafe", "c1", "v1", 1200),
        evidence("P_castle", "c2", "v2", 50, visit="MENTIONED"),  # 언급만 → 순위 제외
        evidence("P_expired", "c2", "v2", 60),
        evidence("P_ichiran", "c3", "v3", 10),  # 실패 영상 → 제외
        evidence("P_cafe", "c2", "v2", 70, version="v0-old"),  # 다른 버전 → 제외
    ]:
        repos.places.put_evidence(item)
    unconfirmed = UnconfirmedMatch(names=["스타벅스"], place_ids=["S1", "S2"])
    _summary(
        repos,
        "v1",
        confirmed=[
            ConfirmedMatch(place_id="P_ichiran", name="이치란 · 도톤보리", category="RESTAURANT")
        ],
        unconfirmed=[unconfirmed],
    )
    _summary(
        repos,
        "v2",
        confirmed=[ConfirmedMatch(place_id="P_ichiran", name="이치란", category="RESTAURANT")],
        unconfirmed=[unconfirmed.model_copy(update={"names": ["스벅", "스타벅스"]})],
    )

    out = _aggregate(repos, settings, job)

    assert (out.status, out.result_s3_key) == ("PARTIAL", result_key(str(job.job_id)))
    _, s3 = aws
    body = json.loads(s3.get_object(Bucket=settings.bucket, Key=out.result_s3_key)["Body"].read())
    assert (body["analyzedChannels"], body["failedVideos"]) == (2, 1)
    assert [(p["placeId"], p["rank"]) for p in body["places"]] == [("P_ichiran", 1), ("P_cafe", 2)]
    ichiran, cafe = body["places"]
    assert ichiran["channels"] == {"visited": 2, "denominator": 2}
    assert ichiran["ratings"]["taste"] == {"positive": 1, "negative": 0, "mixed": 0}
    assert ichiran["ratings"]["wait"] == {"positive": 1, "negative": 1, "mixed": 0}
    assert ichiran["timeEvidence"] == [
        {"kind": "WAIT_EXPERIENCE", "situation": "OPENING", "channels": 1, "recommend": False}
    ]
    assert [e["startSec"] for e in ichiran["evidence"]] == [750, 900, 300]
    assert ichiran["name"] == "이치란 · 도톤보리"  # 1:1 동수 → 채널 ID 순(c1)
    assert (ichiran["areaGroup"], cafe["areaGroup"]) == ("지역 1", "지역 1")
    assert cafe["name"] == "카페"  # 매칭 요약에 없으면 PLACE 아이템의 영상 표기
    assert body["unconfirmed"] == [{"names": ["스타벅스", "스벅"], "reason": "MULTIPLE_BRANCHES"}]

    saved = repos.jobs.require(str(job.job_id))
    assert (saved.status, saved.result_s3_key) == ("PARTIAL", out.result_s3_key)


def test_aggregate_with_no_done_videos_fails(repos: Repos, settings: Settings) -> None:
    job = _job(repos, [ref("v1", "c1", "FAILED"), ref("v2", "c2", "PENDING")])
    out = _aggregate(repos, settings, job)
    assert out.status == "FAILED"
    saved = repos.jobs.require(str(job.job_id))
    assert [r.state for r in saved.video_refs] == ["FAILED", "SKIPPED"]


def _analyzed(repos: Repos, video: str, channel: str) -> None:
    va = repos.video_analysis
    va.claim(video, VERSION, channel_id=channel, job_id="other", now=NOW_EPOCH, lease_sec=900)
    va.record_step(
        video,
        VERSION,
        job_id="other",
        now=NOW_EPOCH,
        lease_sec=900,
        observation_s3_key="o",
        interpretation_s3_key="i",
    )
    va.mark_done(video, VERSION, job_id="other", now=NOW)


def test_replace_prefers_already_analyzed_spare(repos: Repos, settings: Settings) -> None:
    spares = [
        SpareVideo(video_id="s_short", channel_id="c8", duration_sec=300),
        SpareVideo(video_id="s_cached", channel_id="c9", duration_sec=3000),
    ]
    job = _job(repos, [ref("v1", "c1", "FAILED", error="X"), ref("v2", "c2")], spares)
    _analyzed(repos, "s_cached", "c9")

    out = _replace(repos, settings, job)

    assert out.replacement is not None and out.replacement.video_id == "s_cached"
    saved = repos.jobs.require(str(job.job_id))
    assert [(r.video_id, r.state, r.replaces) for r in saved.video_refs] == [
        ("v1", "FAILED", None),
        ("v2", "DONE", None),
        ("s_cached", "PENDING", "v1"),
    ]
    assert [s.video_id for s in saved.spare_videos] == ["s_short"]
    assert saved.progress.total == 3
    # 대체는 작업당 1개
    assert _replace(repos, settings, job).replacement is None


def test_replace_noop_without_failures(repos: Repos, settings: Settings) -> None:
    spares = [SpareVideo(video_id="s1", channel_id="c8", duration_sec=300)]
    job = _job(repos, [ref("v1", "c1")], spares)
    assert _replace(repos, settings, job).replacement is None
    assert len(repos.jobs.require(str(job.job_id)).spare_videos) == 1


def test_successful_replacement_makes_job_succeeded(repos: Repos, settings: Settings) -> None:
    job = _job(repos, [ref("v1", "c1", "FAILED"), ref("v2", "c2"), ref("s1", "c3", replaces="v1")])
    out = _aggregate(repos, settings, job)
    assert out.status == "SUCCEEDED"

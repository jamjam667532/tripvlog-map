"""match 핸들러: 지점 매칭, 근거·좌표 저장, 매칭 요약, Google 응답 미저장."""

import json

from functions.match.handler import Deps, run
from shared.repos import Repos, analysis_key, with_refs
from shared.schemas.events import InterpretOutput
from shared.schemas.interpretation import InterpretationResult
from shared.schemas.items import JobItem, PlaceEvidenceItem, VideoRef
from shared.schemas.match import MatchSummary
from shared.schemas.observation import ObservationResult
from shared.schemas.places import GeoPoint, PlaceHit
from shared.settings import Settings
from tests.fakes import FakePlaces
from tests.integration.factories import (
    NOW,
    NOW_EPOCH,
    V1,
    VERSION,
    guest_job,
    osaka_interpretation,
    osaka_observation,
)

OSAKA = GeoPoint(lat=34.69, lng=135.50)
GOOGLE_NAME = "一蘭 道頓堀店 本館 GOOGLE"
ICHIRAN = PlaceHit(
    place_id="ChIJ_ichiran",
    name=GOOGLE_NAME,
    address="오사카시 주오구 도톤보리 1-4",
    location=GeoPoint(lat=34.6687, lng=135.5013),
)


def _prepare(
    repos: Repos, obs: ObservationResult, interp: InterpretationResult
) -> tuple[JobItem, InterpretOutput]:
    job = guest_job()
    repos.jobs.create(job)
    ref = VideoRef(video_id=V1, channel_id="c1", analysis_version=VERSION, state="ANALYZING")
    repos.jobs.mutate(str(job.job_id), lambda j: with_refs(j, [ref]), NOW)
    repos.video_analysis.claim(
        V1, VERSION, channel_id="c1", job_id=str(job.job_id), now=NOW_EPOCH, lease_sec=900
    )
    obs_key = repos.blobs.put_model(analysis_key(V1, VERSION, "observation"), obs)
    int_key = repos.blobs.put_model(analysis_key(V1, VERSION, "interpretation"), interp)
    repos.video_analysis.record_step(
        V1,
        VERSION,
        job_id=str(job.job_id),
        now=NOW_EPOCH,
        lease_sec=900,
        observation_s3_key=obs_key,
        interpretation_s3_key=int_key,
    )
    event = InterpretOutput(
        job_id=job.job_id,
        video_id=V1,
        channel_id="c1",
        analysis_version=VERSION,
        observation_s3_key=obs_key,
        interpretation_s3_key=int_key,
    )
    return job, event


def _deps(repos: Repos, settings: Settings, places: FakePlaces) -> Deps:
    return Deps(settings=settings, repos=repos, places=places, clock=lambda: NOW)


def test_match_confirms_branch_and_stores_evidence(repos: Repos, settings: Settings) -> None:
    job, event = _prepare(repos, osaka_observation(), osaka_interpretation())
    places = FakePlaces({"一蘭 道頓堀店": [ICHIRAN]}, cities={"오사카": OSAKA})

    run(event, _deps(repos, settings, places))

    [ev] = repos.places.evidence_for_video(V1, VERSION)
    assert ev.place_id == "ChIJ_ichiran" and ev.visit_status == "VISITED"
    assert (ev.video_time_range.start_sec, ev.video_time_range.end_sec) == (750, 905)
    assert ev.clue_types == ["SPEECH", "SCREEN_TEXT"]
    assert ev.evidence_text == "국물 진짜 맛있는데 40분 기다린 건 좀..."
    assert ev.ratings.wait == "NEGATIVE"
    assert [t.kind for t in ev.visit_time_evidence] == ["WAIT_EXPERIENCE"]

    place = repos.places.get_places(["ChIJ_ichiran"])["ChIJ_ichiran"]
    assert (place.extracted_name, place.aliases) == ("이치란", ["一蘭"])
    coord = repos.coords.get_many(["ChIJ_ichiran"], now=NOW_EPOCH)["ChIJ_ichiran"]
    assert (coord.lat, coord.lng) == (34.6687, 135.5013)

    summary = repos.blobs.get_model(analysis_key(V1, VERSION, "match"), MatchSummary)
    assert [(c.place_id, c.name) for c in summary.confirmed] == [
        ("ChIJ_ichiran", "이치란 · 도톤보리")
    ]
    assert (summary.unconfirmed, summary.discarded) == ([], 1)  # 강변 후보는 검색 결과 없음

    va = repos.video_analysis.get(V1, VERSION)
    assert va is not None and va.status == "DONE"
    saved = repos.jobs.require(str(job.job_id))
    assert saved.video_refs[0].state == "DONE"
    assert saved.metrics.places_calls == 3  # 도시 1 + 후보 2개 x 검색어 1개
    assert places.queries == ["오사카", "一蘭 道頓堀店", "道頓堀川"]


def test_match_keeps_multiple_branches_unconfirmed(repos: Repos, settings: Settings) -> None:
    interp = osaka_interpretation()
    c1 = interp.candidates[0].model_copy(update={"branch_hint": None})
    interp = interp.model_copy(update={"candidates": [c1]})
    _, event = _prepare(repos, osaka_observation(), interp)
    other = ICHIRAN.model_copy(update={"place_id": "ChIJ_ichiran2", "address": "남바"})
    places = FakePlaces({"一蘭 道頓堀店": [ICHIRAN, other]}, cities={"오사카": OSAKA})

    run(event, _deps(repos, settings, places))

    assert repos.places.evidence_for_video(V1, VERSION) == []
    summary = repos.blobs.get_model(analysis_key(V1, VERSION, "match"), MatchSummary)
    [u] = summary.unconfirmed
    assert (u.names, u.place_ids) == (["이치란", "一蘭"], ["ChIJ_ichiran", "ChIJ_ichiran2"])


def test_match_replaces_stale_evidence_of_same_version(repos: Repos, settings: Settings) -> None:
    _, event = _prepare(repos, osaka_observation(), osaka_interpretation())
    stale = PlaceEvidenceItem(
        place_id="ChIJ_old",
        sk=PlaceEvidenceItem.make_sk("c1", V1, VERSION, 5),
        video_id=V1,
        channel_id="c1",
        analysis_version=VERSION,
        evidence_key=PlaceEvidenceItem.make_evidence_key("ChIJ_old", VERSION, 5),
        visit_status="VISITED",
        match_status="CONFIRMED",
        video_time_range={"start_sec": 5, "end_sec": 6},
        evidence_text="",
    )
    repos.places.put_evidence(stale)
    run(event, _deps(repos, settings, FakePlaces({"一蘭 道頓堀店": [ICHIRAN]})))
    assert [e.place_id for e in repos.places.evidence_for_video(V1, VERSION)] == ["ChIJ_ichiran"]


def test_match_falls_back_to_names_without_queries(repos: Repos, settings: Settings) -> None:
    interp = osaka_interpretation()
    c1 = interp.candidates[0].model_copy(update={"search_queries": []})
    _, event = _prepare(repos, osaka_observation(), interp.model_copy(update={"candidates": [c1]}))
    places = FakePlaces({"一蘭": [ICHIRAN]})
    run(event, _deps(repos, settings, places))
    assert places.queries == ["오사카", "이치란", "一蘭"]
    assert len(repos.places.evidence_for_video(V1, VERSION)) == 1


def test_match_never_stores_google_name_or_address(
    repos: Repos, settings: Settings, aws: tuple[object, object]
) -> None:
    _, event = _prepare(repos, osaka_observation(), osaka_interpretation())
    run(event, _deps(repos, settings, FakePlaces({"一蘭 道頓堀店": [ICHIRAN]})))

    dynamodb, s3 = aws
    dumped = json.dumps(
        dynamodb.Table(settings.places_table).scan()["Items"],  # type: ignore[attr-defined]
        default=str,
        ensure_ascii=False,
    )
    summary = (
        s3.get_object(  # type: ignore[attr-defined]
            Bucket=settings.bucket, Key=analysis_key(V1, VERSION, "match")
        )["Body"]
        .read()
        .decode()
    )
    for stored in (dumped, summary):
        assert GOOGLE_NAME not in stored
        assert ICHIRAN.address not in stored

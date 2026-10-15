"""shared/repos: DynamoDB·S3 읽기/쓰기와 조건부 쓰기 규칙."""

import threading
from datetime import timedelta

import pytest

from shared.repos import Repos, analysis_key, search_hash, with_metrics, with_ref_state, with_refs
from shared.repos.video_analysis import LeaseLost
from shared.schemas.items import PlaceEvidenceItem, PlaceItem, VideoRef
from shared.schemas.match import ConfirmedMatch, MatchSummary
from shared.schemas.observation import ObservationResult
from shared.schemas.places import GeoPoint
from shared.schemas.youtube import VideoMeta
from tests.integration.factories import NOW, NOW_EPOCH, VERSION, guest_job

LEASE = 900


def _ref(video_id: str, channel_id: str) -> VideoRef:
    return VideoRef(video_id=video_id, channel_id=channel_id, analysis_version=VERSION)


# ---------- Jobs ----------


def test_job_create_get_and_duplicate(repos: Repos) -> None:
    job = guest_job()
    assert repos.jobs.create(job) is True
    assert repos.jobs.create(job) is False
    assert repos.jobs.get(str(job.job_id)) == job
    assert repos.jobs.get("00000000-0000-4000-8000-000000000000") is None


def test_job_find_by_request_id(repos: Repos) -> None:
    job = guest_job()
    repos.jobs.create(job)
    assert repos.jobs.find_by_request_id(str(job.request_id)) == str(job.job_id)


def test_job_mutate_recomputes_progress_and_bumps_updated_at(repos: Repos) -> None:
    job = guest_job()
    repos.jobs.create(job)
    jid = str(job.job_id)
    repos.jobs.mutate(jid, lambda j: with_refs(j, [_ref("v1", "c1"), _ref("v2", "c2")]), NOW)
    updated = repos.jobs.mutate(jid, lambda j: with_ref_state(j, "v1", "DONE"), NOW)
    assert (updated.progress.total, updated.progress.analyzed) == (2, 1)
    assert updated.updated_at > job.updated_at
    updated = repos.jobs.mutate(jid, lambda j: with_metrics(j, gemini_tokens=10), NOW)
    updated = repos.jobs.mutate(jid, lambda j: with_metrics(j, gemini_tokens=5), NOW)
    assert updated.metrics.gemini_tokens == 15


def test_job_mutate_survives_concurrent_writers(repos: Repos) -> None:
    job = guest_job()
    repos.jobs.create(job)
    jid = str(job.job_id)

    def bump() -> None:
        repos.jobs.mutate(jid, lambda j: with_metrics(j, places_calls=1), NOW)

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert repos.jobs.require(jid).metrics.places_calls == 4


def test_job_mutate_rejects_invalid_change(repos: Repos) -> None:
    job = guest_job()
    repos.jobs.create(job)
    # 같은 채널 두 번은 JobItem 검증에 걸린다
    with pytest.raises(ValueError):
        repos.jobs.mutate(
            str(job.job_id), lambda j: with_refs(j, [_ref("v1", "c1"), _ref("v2", "c1")]), NOW
        )


# ---------- VideoAnalysis ----------


def _claim(repos: Repos, job: str, now: int = NOW_EPOCH, video: str = "v1") -> str:
    return repos.video_analysis.claim(
        video, VERSION, channel_id="c1", job_id=job, now=now, lease_sec=LEASE
    )


def test_claim_new_then_wait_then_reuse(repos: Repos) -> None:
    va = repos.video_analysis
    assert _claim(repos, "job-a") == "ANALYZE"
    assert _claim(repos, "job-b") == "WAIT"
    assert _claim(repos, "job-a") == "ANALYZE"  # 같은 작업의 재시도
    va.record_step(
        "v1",
        VERSION,
        job_id="job-a",
        now=NOW_EPOCH,
        lease_sec=LEASE,
        observation_s3_key="o",
        interpretation_s3_key="i",
        gemini_tokens=7,
    )
    done = va.mark_done("v1", VERSION, job_id="job-a", now=NOW)
    assert done.status == "DONE" and done.lock_owner is None and done.usage.gemini_tokens == 7
    assert _claim(repos, "job-b") == "REUSE"


def test_claim_takes_over_expired_lease_and_failed(repos: Repos) -> None:
    va = repos.video_analysis
    assert _claim(repos, "job-a") == "ANALYZE"
    assert _claim(repos, "job-b", now=NOW_EPOCH + LEASE) == "ANALYZE"
    # 선점을 잃은 작업은 결과를 쓰지 못한다
    with pytest.raises(LeaseLost):
        va.mark_done("v1", VERSION, job_id="job-a", now=NOW)
    assert va.mark_failed("v1", VERSION, job_id="job-a") is False
    assert va.mark_failed("v1", VERSION, job_id="job-b") is True
    assert _claim(repos, "job-c") == "ANALYZE"


def test_claim_race_has_single_winner(repos: Repos) -> None:
    results: list[str] = []
    lock = threading.Lock()

    def run(i: int) -> None:
        r = _claim(repos, f"job-{i}")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ANALYZE"] + ["WAIT"] * 5


def test_done_video_ids(repos: Repos) -> None:
    va = repos.video_analysis
    _claim(repos, "j", video="v1")
    _claim(repos, "j", video="v2")
    va.record_step(
        "v1",
        VERSION,
        job_id="j",
        now=NOW_EPOCH,
        lease_sec=LEASE,
        observation_s3_key="o",
        interpretation_s3_key="i",
    )
    va.mark_done("v1", VERSION, job_id="j", now=NOW)
    assert va.done_video_ids(["v1", "v2", "v3"], VERSION) == {"v1"}
    assert va.done_video_ids([], VERSION) == set()


# ---------- Places / CoordCache ----------


def _evidence(place: str, video: str, start: int, version: str = VERSION) -> PlaceEvidenceItem:
    return PlaceEvidenceItem(
        place_id=place,
        sk=PlaceEvidenceItem.make_sk("c1", video, version, start),
        video_id=video,
        channel_id="c1",
        analysis_version=version,
        evidence_key=PlaceEvidenceItem.make_evidence_key(place, version, start),
        visit_status="VISITED",
        match_status="CONFIRMED",
        video_time_range={"start_sec": start, "end_sec": start + 5},
        evidence_text="맛있다",
        visit_time_evidence=[
            {
                "kind": "STATED_TIME",
                "situation": "MORNING",
                "local_clock_time": "09:00",
                "evidence_text": "9시",
            }
        ],
    )


def test_places_evidence_by_video_filters_version(repos: Repos) -> None:
    p = repos.places
    p.put_evidence(_evidence("P1", "v1", 10))
    p.put_evidence(_evidence("P2", "v1", 20))
    p.put_evidence(_evidence("P1", "v1", 10, version="v0-old"))
    p.put_evidence(_evidence("P1", "v2", 30))
    found = p.evidence_for_video("v1", VERSION)
    assert sorted(e.place_id for e in found) == ["P1", "P2"]
    assert found[0].visit_time_evidence[0].local_clock_time == "09:00"
    assert p.delete_evidence_for_video("v1", VERSION) == 2
    assert p.evidence_for_video("v1", VERSION) == []
    assert len(p.evidence_for_video("v1", "v0-old")) == 1


def test_place_item_keeps_first_name(repos: Repos) -> None:
    first = PlaceItem(
        place_id="P1",
        destination="오사카",
        extracted_name="이치란",
        category_from_video="RESTAURANT",
    )
    assert repos.places.put_place_if_absent(first) is True
    assert (
        repos.places.put_place_if_absent(first.model_copy(update={"extracted_name": "一蘭"}))
        is False
    )
    assert repos.places.get_places(["P1", "P9"]) == {"P1": first}


def test_coord_cache_float_roundtrip_and_expiry(repos: Repos) -> None:
    c = repos.coords
    c.put("P1", GeoPoint(lat=34.6687, lng=135.5013), now=NOW_EPOCH, ttl_days=25)
    got = c.get_many(["P1"], now=NOW_EPOCH)
    assert (got["P1"].lat, got["P1"].lng) == (34.6687, 135.5013)
    assert c.get_many(["P1"], now=NOW_EPOCH + 25 * 86_400) == {}


# ---------- YoutubeCache ----------


def test_youtube_search_and_video_cache(repos: Repos) -> None:
    y = repos.youtube_cache
    digest = search_hash({"q": "오사카 브이로그", "order": "relevance"})
    assert digest == search_hash({"order": "relevance", "q": "오사카 브이로그"})
    assert y.get_search(digest, now=NOW_EPOCH) is None
    y.put_search(digest, ["v1", "v2"], now=NOW_EPOCH, ttl_days=25)
    assert y.get_search(digest, now=NOW_EPOCH) == ["v1", "v2"]
    assert y.get_search(digest, now=NOW_EPOCH + 26 * 86_400) is None

    meta = VideoMeta(
        video_id="v1",
        channel_id="c1",
        title="오사카",
        description="",
        duration_sec=600,
        privacy_status="public",
        published_at=NOW - timedelta(days=10),
    )
    y.put_video(meta, now=NOW_EPOCH, ttl_days=25)
    assert y.get_videos(["v1", "v2"], now=NOW_EPOCH) == {"v1": meta}


def test_youtube_daily_search_quota(repos: Repos) -> None:
    y = repos.youtube_cache
    assert [y.take_search_quota("2026-10-15", limit=2, now=NOW_EPOCH) for _ in range(3)] == [
        True,
        True,
        False,
    ]
    assert y.take_search_quota("2026-10-16", limit=2, now=NOW_EPOCH) is True


# ---------- S3 ----------


def test_blob_roundtrip_ai_and_camel_models(repos: Repos) -> None:
    obs = ObservationResult.model_validate(
        {"video_id": "v1", "clues": [{"start_sec": 1, "end_sec": 2, "clue_type": "SPEECH"}]}
    )
    key = repos.blobs.put_model(analysis_key("v1", VERSION, "observation"), obs)
    assert key == f"analysis/v1/{VERSION}/observation.json"
    assert repos.blobs.get_model(key, ObservationResult) == obs

    summary = MatchSummary(
        video_id="v1",
        analysis_version=VERSION,
        confirmed=[ConfirmedMatch(place_id="P1", name="이치란 · 도톤보리", category="RESTAURANT")],
    )
    key = repos.blobs.put_model(analysis_key("v1", VERSION, "match"), summary)
    assert repos.blobs.get_model(key, MatchSummary) == summary

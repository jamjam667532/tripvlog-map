"""collect 핸들러: 검색 캐시, 일일 상한, 규칙 필터, videoRefs·spareVideos 기록."""

from dataclasses import replace
from datetime import timedelta

from functions.collect.handler import Deps, run
from shared.repos import Repos
from shared.schemas.events import JobInput
from shared.schemas.youtube import VideoMeta
from shared.settings import Settings
from tests.fakes import FakeYouTube
from tests.integration.factories import NOW, guest_job


def meta(vid: str, ch: str, *, minutes: int = 15, title: str = "오사카 브이로그") -> VideoMeta:
    return VideoMeta(
        video_id=vid,
        channel_id=ch,
        title=title,
        description="",
        duration_sec=minutes * 60,
        privacy_status="public",
        published_at=NOW - timedelta(days=30),
    )


METAS = [
    meta("v1", "c1"),
    meta("v2", "c2", title="오사카 맛집 투어"),
    meta("v3", "c3", minutes=2),  # 3분 미만 → 제외
    meta("v4", "c1"),  # 같은 채널 → 제외
    meta("v5", "c5"),
    meta("v6", "c6"),
    meta("v7", "c7", minutes=40),
    meta("v8", "c8", minutes=8),
    meta("v9", "c9"),
]
SEARCH = {
    "오사카 브이로그": ["v1", "v3", "v5", "v7"],
    "오사카 맛집": ["v2", "v4", "v6", "v8"],
    "오사카 여행": ["v1", "v9"],
}


def _deps(repos: Repos, settings: Settings, youtube: FakeYouTube) -> Deps:
    return Deps(settings=settings, repos=repos, youtube=youtube, clock=lambda: NOW)


def test_collect_selects_five_and_three_spares(repos: Repos, settings: Settings) -> None:
    job = guest_job()
    repos.jobs.create(job)
    youtube = FakeYouTube(SEARCH, METAS)

    out = run(JobInput(job_id=job.job_id), _deps(repos, settings, youtube))

    # 맛집 영상(v2)이 앞으로, 나머지는 번갈아 합친 검색 순서
    assert [r.video_id for r in out.video_refs] == ["v2", "v1", "v9", "v5", "v6"]
    assert all(r.job_id == job.job_id for r in out.video_refs)
    saved = repos.jobs.require(str(job.job_id))
    assert saved.status == "RUNNING"
    assert [r.state for r in saved.video_refs] == ["PENDING"] * 5
    assert [s.video_id for s in saved.spare_videos] == ["v7", "v8"]
    assert saved.progress.total == 5
    assert youtube.search_calls == [
        ("오사카 브이로그", "relevance"),
        ("오사카 맛집", "relevance"),
        ("오사카 여행", "date"),
    ]
    assert saved.metrics.youtube_units == 3 * 100 + 1


def test_collect_uses_cache_for_second_job(repos: Repos, settings: Settings) -> None:
    youtube = FakeYouTube(SEARCH, METAS)
    deps = _deps(repos, settings, youtube)
    first, second = guest_job(), guest_job()
    for j in (first, second):
        repos.jobs.create(j)
    run(JobInput(job_id=first.job_id), deps)
    out = run(JobInput(job_id=second.job_id), deps)

    assert len(youtube.search_calls) == 3  # 두 번째 작업은 검색·메타 모두 캐시
    assert len(out.video_refs) == 5
    assert repos.jobs.require(str(second.job_id)).metrics.youtube_units == 0


def test_collect_is_idempotent_on_retry(repos: Repos, settings: Settings) -> None:
    youtube = FakeYouTube(SEARCH, METAS)
    deps = _deps(repos, settings, youtube)
    job = guest_job()
    repos.jobs.create(job)
    first = run(JobInput(job_id=job.job_id), deps)
    again = run(JobInput(job_id=job.job_id), deps)
    assert first == again
    assert len(youtube.search_calls) == 3


def test_collect_daily_search_limit_falls_back_to_cache(repos: Repos, settings: Settings) -> None:
    youtube = FakeYouTube(SEARCH, METAS)
    deps = _deps(repos, replace(settings, daily_search_limit=1), youtube)
    job = guest_job()
    repos.jobs.create(job)
    out = run(JobInput(job_id=job.job_id), deps)

    assert len(youtube.search_calls) == 1  # 상한 1회 → 첫 검색만
    assert [r.video_id for r in out.video_refs] == ["v1", "v5", "v7"]


def test_collect_with_no_results_leaves_empty_refs(repos: Repos, settings: Settings) -> None:
    job = guest_job(destination="없는도시")
    repos.jobs.create(job)
    out = run(JobInput(job_id=job.job_id), _deps(repos, settings, FakeYouTube({}, [])))
    assert out.video_refs == []
    assert repos.jobs.require(str(job.job_id)).progress.total == 0

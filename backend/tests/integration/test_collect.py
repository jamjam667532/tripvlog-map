"""collect 핸들러: 검색 캐시, 일일 상한, 규칙 필터, videoRefs·spareVideos 기록."""

from dataclasses import replace
from datetime import timedelta

from functions.collect.handler import Deps, run
from shared.repos import Repos
from shared.schemas.events import JobInput
from shared.schemas.items import UserItem, UserPreferences, YoutubeLink
from shared.schemas.taste import ChannelVideo
from shared.schemas.youtube import VideoMeta
from shared.settings import Settings
from tests.fakes import FakeYouTube
from tests.integration.factories import NOW, NOW_EPOCH, VERSION, guest_job


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
    meta("v7", "c7", minutes=25),  # 30분 상한 안(결정 0006-5)
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


# ---------- 로그인 작업: 개인 채널 영상 (결정 0010) ----------

USER = "google:u1"
PERSONAL = [meta("p1", "pc1", title="오사카 3박 4일"), meta("p2", "pc2", title="오사카 야경")]
UPLOADS = {
    "pc1": [ChannelVideo(video_id="p1", channel_id="pc1", title="오사카 3박 4일")],
    "pc2": [
        ChannelVideo(video_id="x9", channel_id="pc2", title="도쿄 브이로그"),  # 다른 도시
        ChannelVideo(video_id="p2", channel_id="pc2", title="오사카 야경"),
    ],
}


def _analyzed(repos: Repos, video: str, channel: str) -> None:
    va = repos.video_analysis
    va.claim(video, VERSION, channel_id=channel, job_id="old", now=NOW_EPOCH, lease_sec=900)
    va.record_step(
        video,
        VERSION,
        job_id="old",
        now=NOW_EPOCH,
        lease_sec=900,
        observation_s3_key="o",
        interpretation_s3_key="i",
    )
    va.mark_done(video, VERSION, job_id="old", now=NOW)


def _user_job(repos: Repos) -> str:
    job = guest_job(guestAccessHash=None, userId=USER)
    repos.jobs.create(job)
    repos.users.put(
        UserItem(user_id=USER, preferences=UserPreferences(reference_channel_ids=["pc1", "pc2"]))
    )
    return str(job.job_id)


def test_login_job_puts_already_analyzed_personal_videos_first(
    repos: Repos, settings: Settings
) -> None:
    _analyzed(repos, "p1", "pc1")
    _analyzed(repos, "p2", "pc2")
    job_id = _user_job(repos)
    youtube = FakeYouTube(SEARCH, METAS + PERSONAL, uploads=UPLOADS)
    out = run(JobInput.model_validate({"jobId": job_id}), _deps(repos, settings, youtube))
    ids = [r.video_id for r in out.video_refs]
    assert ids[:2] == ["p1", "p2"] and len(ids) == settings.max_videos_per_job
    assert youtube.upload_calls == ["pc1", "pc2"]


def test_personal_videos_not_yet_analyzed_are_added_after_analyzed_ones(
    repos: Repos, settings: Settings
) -> None:
    """결정 0010 개정: 분석된 적 없는 개인 영상도 넣는다(실시간 분석). 분석된 것이 먼저."""
    _analyzed(repos, "p2", "pc2")
    job_id = _user_job(repos)
    youtube = FakeYouTube(SEARCH, METAS + PERSONAL, uploads=UPLOADS)
    out = run(JobInput.model_validate({"jobId": job_id}), _deps(repos, settings, youtube))
    ids = [r.video_id for r in out.video_refs]
    assert ids[:2] == ["p2", "p1"]
    assert len(ids) == settings.max_videos_per_job  # 개인 영상이 일반 영상 자리를 대신한다


def test_channel_prefers_its_already_analyzed_video(repos: Repos, settings: Settings) -> None:
    newer = meta("p1new", "pc1", title="오사카 신상 맛집")
    uploads = {
        **UPLOADS,
        "pc1": [
            ChannelVideo(video_id="p1new", channel_id="pc1", title="오사카 신상 맛집"),
            ChannelVideo(video_id="p1", channel_id="pc1", title="오사카 3박 4일"),
        ],
    }
    _analyzed(repos, "p1", "pc1")
    job_id = _user_job(repos)
    youtube = FakeYouTube(SEARCH, [*METAS, *PERSONAL, newer], uploads=uploads)
    out = run(JobInput.model_validate({"jobId": job_id}), _deps(repos, settings, youtube))
    ids = [r.video_id for r in out.video_refs]
    assert ids[0] == "p1" and "p1new" not in ids  # 채널당 1개, 분석된 영상이 이긴다


def test_guest_job_does_not_look_at_personal_channels(repos: Repos, settings: Settings) -> None:
    job = guest_job()
    repos.jobs.create(job)
    youtube = FakeYouTube(SEARCH, METAS, uploads=UPLOADS)
    run(JobInput(job_id=job.job_id), _deps(repos, settings, youtube))
    assert youtube.upload_calls == []


def test_auto_profile_from_youtube_is_used_without_any_user_edit(
    repos: Repos, settings: Settings
) -> None:
    """결정 0010 개정: 유튜브 연결만 하면(수정 없음) 자동 프로필로 고른다."""
    job = guest_job(guestAccessHash=None, userId=USER)
    repos.jobs.create(job)
    link = YoutubeLink.model_validate(
        {
            "linked": True,
            "syncedAt": NOW.isoformat(),
            "resyncDueAt": NOW.isoformat(),
            "travelChannelIds": ["pc1"],
            "styleProfileCandidate": {"맛집": 1.0},
        }
    )
    repos.users.put(UserItem(user_id=USER, youtube=link))
    youtube = FakeYouTube(SEARCH, METAS + PERSONAL, uploads=UPLOADS)
    out = run(JobInput.model_validate({"jobId": str(job.job_id)}), _deps(repos, settings, youtube))
    ids = [r.video_id for r in out.video_refs]
    assert ids[0] == "p1"  # 구독 여행 채널 영상(새로 분석)
    assert ids[1] == "v2"  # 일반 후보 중 맛집 영상이 유사도 1순위
    assert youtube.upload_calls == ["pc1"]

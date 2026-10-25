"""[1] collect: 목적지로 영상 후보를 찾고 분석할 영상 5개 + 예비 3개를 고른다 (spec §5.1).

입력 {jobId} → 출력 {jobId, videoRefs:[{jobId, videoId, channelId, analysisVersion}]}
YouTube 검색 결과·메타데이터는 YoutubeCache(25일)를 먼저 본다. 조회수 등 지표는 쓰지 않는다.
"""

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from shared.clients.secrets import get_secret
from shared.clients.youtube import SearchOrder, YouTubeClient, YouTubeDataApi
from shared.repos import Repos, search_hash, with_metrics, with_refs
from shared.rules.selection import merge_round_robin, select_videos
from shared.schemas.events import CollectOutput, JobInput, VideoTask
from shared.schemas.items import JobItem, SpareVideo, VideoRef
from shared.schemas.youtube import VideoMeta
from shared.settings import Settings

# TODO(decision 0004-7): 정렬 혼합 방식
SEARCH_PLAN: tuple[tuple[str, SearchOrder], ...] = (
    ("{dest} 브이로그", "relevance"),
    ("{dest} 맛집", "relevance"),
    ("{dest} 여행", "date"),
)
MAX_RESULTS = 25
SEARCH_YEARS = 2


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    youtube: YouTubeClient
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def published_after(now: datetime) -> datetime:
    """2년 전 달의 1일. 캐시 해시가 매일 바뀌지 않게 달 단위로 맞춘다(결정 0004-7)."""
    return datetime(now.year - SEARCH_YEARS, now.month, 1, tzinfo=UTC)


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _search(deps: Deps, query: str, order: SearchOrder, after: datetime, now: int) -> list[str]:
    s = deps.settings
    cache = deps.repos.youtube_cache
    digest = search_hash(
        {
            "query": _normalize(query),
            "order": order,
            "page": 1,
            "maxResults": MAX_RESULTS,
            "language": "ko",
            "publishedAfter": after.date().isoformat(),
        }
    )
    cached = cache.get_search(digest, now=now)
    if cached is not None:
        return cached
    day = datetime.fromtimestamp(now, UTC).date().isoformat()
    if not cache.take_search_quota(day, limit=s.daily_search_limit, now=now):
        return []  # 오늘 검색 상한 도달 → 캐시만 쓴다
    ids = deps.youtube.search(query, order=order, published_after=after, max_results=MAX_RESULTS)
    cache.put_search(digest, ids, now=now, ttl_days=s.youtube_cache_ttl_days)
    return ids


def _metas(deps: Deps, video_ids: list[str], now: int) -> dict[str, VideoMeta]:
    cache = deps.repos.youtube_cache
    found = cache.get_videos(video_ids, now=now)
    missing = [v for v in video_ids if v not in found]
    if missing:
        for meta in deps.youtube.videos(missing):
            cache.put_video(meta, now=now, ttl_days=deps.settings.youtube_cache_ttl_days)
            found[meta.video_id] = meta
    return found


def _output(job: JobItem) -> CollectOutput:
    return CollectOutput(
        job_id=job.job_id,
        video_refs=[
            VideoTask(
                job_id=job.job_id,
                video_id=r.video_id,
                channel_id=r.channel_id,
                analysis_version=r.analysis_version,
            )
            for r in job.video_refs
        ],
    )


def run(event: JobInput, deps: Deps) -> CollectOutput:
    s = deps.settings
    job_id = str(event.job_id)
    now_dt = deps.clock()
    job = deps.repos.jobs.mutate(
        job_id, lambda j: j.model_copy(update={"status": "RUNNING"}), now_dt
    )
    if job.video_refs:
        return _output(job)  # Step Functions 재시도: 이미 고른 영상을 그대로 쓴다

    now = int(now_dt.timestamp())
    dest = job.request.destination
    after = published_after(now_dt)
    units_before = int(getattr(deps.youtube, "units_used", 0))
    results = [_search(deps, q.format(dest=dest), order, after, now) for q, order in SEARCH_PLAN]
    ids = merge_round_robin(results)
    metas = _metas(deps, ids, now)
    picked = select_videos(
        (metas[v] for v in ids if v in metas),
        now=now_dt,
        preferred_styles=job.request.styles,
        destination=dest,
        max_videos=s.max_videos_per_job,
        max_spares=s.spare_videos_per_job,
    )
    refs = [
        VideoRef(video_id=m.video_id, channel_id=m.channel_id, analysis_version=s.analysis_version)
        for m in picked.chosen
    ]
    spares = [
        SpareVideo(video_id=m.video_id, channel_id=m.channel_id, duration_sec=m.duration_sec)
        for m in picked.spares
    ]
    units = int(getattr(deps.youtube, "units_used", 0)) - units_before

    def record(j: JobItem) -> JobItem:
        j = with_refs(j, refs).model_copy(update={"spare_videos": spares})
        return with_metrics(j, youtube_units=units)

    return _output(deps.repos.jobs.mutate(job_id, record, deps.clock()))


@lru_cache(maxsize=1)
def _deps() -> Deps:
    settings = Settings.from_env()
    return Deps(
        settings=settings,
        repos=Repos.from_settings(settings),
        youtube=YouTubeDataApi(get_secret(settings.youtube_key_param)),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run(JobInput.model_validate(event), _deps()).model_dump(mode="json")

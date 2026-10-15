"""observe: Gemini로 영상을 관찰한다 (spec §5.2). 영상은 내려받지 않고 공개 YouTube URL만 넘긴다.

입력 VideoTask → 관찰 결과를 S3 analysis/{videoId}/{version}/observation.json에 쓰고 키만 돌려준다.
검증 실패 재요청은 클라이언트가 1회 한다. 그래도 실패하면 예외 → Step Functions Catch → claim(fail).
Gemini 전역 동시 호출 수는 이 Lambda의 예약 동시성으로 제한한다(M5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from shared.clients.gemini import GeminiObserver, GeminiYouTubeObserver
from shared.clients.secrets import get_secret
from shared.repos import Repos, analysis_key, with_metrics
from shared.schemas.events import ObserveOutput, VideoTask
from shared.settings import Settings, require


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    gemini: GeminiObserver
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def run(event: VideoTask, deps: Deps) -> ObserveOutput:
    observation = deps.gemini.observe(event.video_id)
    key = deps.repos.blobs.put_model(
        analysis_key(event.video_id, event.analysis_version, "observation"), observation.result
    )
    now = deps.clock()
    deps.repos.video_analysis.record_step(
        event.video_id,
        event.analysis_version,
        job_id=str(event.job_id),
        now=int(now.timestamp()),
        lease_sec=deps.settings.lease_sec,
        observation_s3_key=key,
        gemini_tokens=observation.tokens,
    )
    deps.repos.jobs.mutate(
        str(event.job_id), lambda j: with_metrics(j, gemini_tokens=observation.tokens), now
    )
    return ObserveOutput(**event.task_fields(), observation_s3_key=key)


@lru_cache(maxsize=1)
def _deps() -> Deps:
    s = Settings.from_env()
    return Deps(
        settings=s,
        repos=Repos.from_settings(s),
        gemini=GeminiYouTubeObserver(
            require(s.gemini_model, "GEMINI_MODEL"),
            api_key=get_secret(s.gemini_key_param),
            media_resolution=s.gemini_media_resolution,
        ),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run(VideoTask.model_validate(event), _deps()).model_dump(mode="json")

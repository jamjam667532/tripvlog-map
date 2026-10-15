"""claim: 영상 분석 선점과 실패 기록 (spec §4.2, 결정 0004-1·2).

action=claim (기본)
  VideoAnalysis 조건부 선점 → ANALYZE(분석 진행) / REUSE(이미 DONE, 분석 생략)
  / WAIT(다른 작업이 분석 중).
  WAIT이면 Step Functions가 30초 기다린 뒤 다시 부른다. MAX_CLAIM_WAITS번을 넘으면 실패.
action=fail
  Map 항목 Catch에서 부른다. Jobs 영상은 FAILED로, VideoAnalysis는 이 작업이 선점한 경우에만
  FAILED로 바꾼다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from shared.repos import Repos, with_ref_state
from shared.schemas.api import VideoState
from shared.schemas.events import ClaimInput, ClaimOutput, FailInput, FailOutput
from shared.settings import Settings

ERROR_CODE_MAX = 64


class ClaimWaitTimeout(Exception):
    """다른 작업의 분석을 너무 오래 기다렸다."""


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def claim(event: ClaimInput, deps: Deps) -> ClaimOutput:
    s = deps.settings
    now = deps.clock()
    decision = deps.repos.video_analysis.claim(
        event.video_id,
        event.analysis_version,
        channel_id=event.channel_id,
        job_id=str(event.job_id),
        now=int(now.timestamp()),
        lease_sec=s.lease_sec,
    )
    if decision == "WAIT":
        if event.wait_count >= s.max_claim_waits:
            raise ClaimWaitTimeout(event.video_id)
        return ClaimOutput(**event.task_fields(), decision="WAIT", wait_count=event.wait_count + 1)

    state: VideoState = "ANALYZING" if decision == "ANALYZE" else "DONE"
    deps.repos.jobs.mutate(
        str(event.job_id), lambda j: with_ref_state(j, event.video_id, state), now
    )
    return ClaimOutput(**event.task_fields(), decision=decision, wait_count=event.wait_count)


def fail(event: FailInput, deps: Deps) -> FailOutput:
    job_id = str(event.job_id)
    deps.repos.video_analysis.mark_failed(event.video_id, event.analysis_version, job_id=job_id)
    # Cause에는 원문이 섞일 수 있어 오류 이름만 남긴다
    code = event.error.Error[:ERROR_CODE_MAX]
    deps.repos.jobs.mutate(
        job_id, lambda j: with_ref_state(j, event.video_id, "FAILED", error=code), deps.clock()
    )
    return FailOutput(**event.task_fields())


def run(event: dict[str, Any], deps: Deps) -> ClaimOutput | FailOutput:
    if event.get("action") == "fail":
        return fail(FailInput.model_validate(event), deps)
    return claim(ClaimInput.model_validate(event), deps)


@lru_cache(maxsize=1)
def _deps() -> Deps:
    settings = Settings.from_env()
    return Deps(settings=settings, repos=Repos.from_settings(settings))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run(event, _deps()).model_dump(mode="json")

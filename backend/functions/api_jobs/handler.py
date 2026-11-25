"""[M8] api_jobs: 로그인 사용자의 작업 (spec §3.3, 결정 0010). HTTP API 페이로드 2.0.

사용자는 JWT Authorizer가 검증한 토큰의 sub로만 정한다(google:<sub>).
요청 본문의 userId는 받지 않는다. 게스트 경로(api_public)와 작업 만들기·실행·조회는 같고
(functions/job_api.py), 다른 점은 아래뿐이다.

POST /jobs                 게스트 토큰 대신 userId로 작업을 묶는다.
                           요청 스타일·동행이 비어 있으면 저장된 선호를 기본값으로 쓴다
GET  /jobs/{jobId}         본인 작업만. 남의 작업이면 404(존재 여부를 숨긴다)
POST /jobs/{jobId}/rerank  끝난 작업의 순위만 다른 스타일로 다시 계산한다.
                           분석·AI 호출 없음, 저장 안 함
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from pydantic import ValidationError

from functions.aggregate import handler as aggregate_fn
from functions.job_api import (
    Unauthorized,
    error,
    job_id_for,
    job_view,
    json_body,
    not_found,
    path_job_id,
    response,
    start_job,
    user_id_of,
)
from shared.clients.orchestrator import JobStarter, StepFunctionsStarter
from shared.repos import Repos
from shared.schemas.api import (
    TERMINAL_STATUSES,
    CreateJobRequest,
    CreateJobResponse,
    GetJobResponse,
    RerankRequest,
)
from shared.schemas.items import JobItem, JobRequestSpec
from shared.settings import Settings, require

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    starter: JobStarter
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def _own_job(event: dict[str, Any], user_id: str, deps: Deps) -> JobItem | None:
    job_id = path_job_id(event)
    job = deps.repos.jobs.get(job_id) if job_id else None
    return job if job is not None and job.user_id == user_id else None


def create_job(event: dict[str, Any], user_id: str, deps: Deps) -> dict[str, Any]:
    try:
        req = CreateJobRequest.model_validate(json_body(event))
    except (ValueError, ValidationError):
        return error(400, "INVALID_REQUEST", "request body is invalid")

    saved = deps.repos.users.get(user_id)
    styles = req.styles or (saved.preferences.styles if saved else [])
    companion = req.companion or (saved.preferences.companion if saved else None)
    now = deps.clock()
    job = JobItem(
        job_id=job_id_for(req.request_id),
        request_id=req.request_id,
        user_id=user_id,
        status="QUEUED",
        request=JobRequestSpec(destination=req.destination, styles=styles, companion=companion),
        created_at=now,
        updated_at=now,
    )
    failed = start_job(job, deps.repos, deps.starter, deps.clock)
    if failed is not None:
        return failed
    return response(202, CreateJobResponse(job_id=job.job_id, status="QUEUED"))


def get_job(event: dict[str, Any], user_id: str, deps: Deps) -> dict[str, Any]:
    job = _own_job(event, user_id, deps)
    if job is None:
        return not_found()
    return response(200, job_view(job, deps.repos.blobs))


def rerank_job(event: dict[str, Any], user_id: str, deps: Deps) -> dict[str, Any]:
    job = _own_job(event, user_id, deps)
    if job is None:
        return not_found()
    if job.status not in TERMINAL_STATUSES:
        return error(409, "NOT_FINISHED", "analysis is still running", job_id=job.job_id)
    try:
        req = RerankRequest.model_validate(json_body(event))
    except (ValueError, ValidationError):
        return error(400, "INVALID_REQUEST", "request body is invalid")
    spec = job.request.model_copy(update={"styles": req.styles, "companion": req.companion})
    result = aggregate_fn.build_result(
        job.model_copy(update={"request": spec}),
        aggregate_fn.Deps(settings=deps.settings, repos=deps.repos, clock=deps.clock),
        deps.clock(),
    )
    view = job_view(job, deps.repos.blobs)
    return response(
        200,
        GetJobResponse(
            job_id=view.job_id,
            status=view.status,
            progress=view.progress,
            videos=view.videos,
            result=result,
            result_stage="FINAL",
        ),
    )


ROUTES: dict[str, Callable[[dict[str, Any], str, Deps], dict[str, Any]]] = {
    "POST /jobs": create_job,
    "GET /jobs/{jobId}": get_job,
    "POST /jobs/{jobId}/rerank": rerank_job,
}


def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return error(404, "NOT_FOUND", "route not found")
    try:
        user_id = user_id_of(event)
    except Unauthorized:
        return error(401, "UNAUTHORIZED", "login required")
    try:
        return route(event, user_id, deps)
    except Exception:
        logger.exception("api_jobs failed")
        return error(500, "INTERNAL", "internal error")


@lru_cache(maxsize=1)
def _deps() -> Deps:
    s = Settings.from_env()
    return Deps(
        settings=s,
        repos=Repos.from_settings(s),
        starter=StepFunctionsStarter(require(s.state_machine_arn, "STATE_MACHINE_ARN")),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run(event, _deps())

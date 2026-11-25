"""[0] api_public: 비로그인 경로 (spec §3.1·3.2). API Gateway HTTP API 페이로드 2.0.

POST /public/jobs
  같은 requestId는 같은 jobId → 조건부 쓰기로 중복을 원자적으로 막는다(결정 0004-6). 중복이면 409.
  guestAccessToken은 응답에서 한 번만 돌려주고 DB에는 sha256만 저장한다.
GET /public/jobs/{jobId}
  X-Guest-Access-Token 해시가 맞지 않거나 없으면 404(존재 여부를 숨긴다). 비교는 상수 시간.
  종료 상태면 S3 결과 JSON을 읽어 담는다(S3 URL은 노출하지 않는다).

요청 제한(IP·전역 일일 예산, 429)은 M5에서 API Gateway와 함께 붙인다(결정 0004-7).
로그에 토큰을 남기지 않는다.
"""

import hashlib
import hmac
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from pydantic import ValidationError

from functions.job_api import (
    error,
    job_id_for,
    job_view,
    json_body,
    not_found,
    path_job_id,
    response,
    start_job,
)
from shared.clients.orchestrator import JobStarter, StepFunctionsStarter
from shared.repos import Repos
from shared.schemas.api import (
    CreateJobRequest,
    CreateJobResponse,
)
from shared.schemas.items import JobItem, JobRequestSpec
from shared.settings import Settings, require

logger = logging.getLogger(__name__)

TOKEN_HEADER = "x-guest-access-token"


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    starter: JobStarter
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_job(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    try:
        req = CreateJobRequest.model_validate(json_body(event))
    except (ValueError, ValidationError):
        # 입력값을 그대로 돌려주지 않는다
        return error(400, "INVALID_REQUEST", "request body is invalid")

    now = deps.clock()
    job_id = job_id_for(req.request_id)
    token = secrets.token_urlsafe(32)
    job = JobItem(
        job_id=job_id,
        request_id=req.request_id,
        guest_access_hash=hash_token(token),
        status="QUEUED",
        request=JobRequestSpec(
            destination=req.destination, styles=req.styles, companion=req.companion
        ),
        created_at=now,
        updated_at=now,
    )
    failed = start_job(job, deps.repos, deps.starter, deps.clock)
    if failed is not None:
        return failed
    return response(
        202, CreateJobResponse(job_id=job_id, guest_access_token=token, status="QUEUED")
    )


def get_job(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    job_id = path_job_id(event)
    token = (event.get("headers") or {}).get(TOKEN_HEADER)
    if job_id is None or not token:
        return not_found()
    job = deps.repos.jobs.get(job_id)
    if job is None or job.guest_access_hash is None:
        return not_found()
    if not hmac.compare_digest(hash_token(token), job.guest_access_hash):
        return not_found()
    return response(200, job_view(job, deps.repos.blobs))


ROUTES: dict[str, Callable[[dict[str, Any], Deps], dict[str, Any]]] = {
    "POST /public/jobs": create_job,
    "GET /public/jobs/{jobId}": get_job,
}


def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return error(404, "NOT_FOUND", "route not found")
    try:
        return route(event, deps)
    except Exception:
        logger.exception("unhandled error")
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

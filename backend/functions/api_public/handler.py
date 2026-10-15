"""api_public: 비로그인 경로 (spec §3.1·3.2). API Gateway HTTP API 페이로드 2.0.

POST /public/jobs
  같은 requestId는 같은 jobId → 조건부 쓰기로 중복을 원자적으로 막는다(결정 0004-6). 중복이면 409.
  guestAccessToken은 응답에서 한 번만 돌려주고 DB에는 sha256만 저장한다.
GET /public/jobs/{jobId}
  X-Guest-Access-Token 해시가 맞지 않거나 없으면 404(존재 여부를 숨긴다). 비교는 상수 시간.
  종료 상태면 S3 결과 JSON을 읽어 담는다(S3 URL은 노출하지 않는다).

요청 제한(IP·전역 일일 예산, 429)은 M5에서 API Gateway와 함께 붙인다(결정 0004-7).
로그에 토큰을 남기지 않는다.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ValidationError

from shared.clients.orchestrator import JobStarter, StepFunctionsStarter
from shared.repos import Repos
from shared.schemas.api import (
    TERMINAL_STATUSES,
    CreateJobRequest,
    CreateJobResponse,
    ErrorBody,
    ErrorResponse,
    GetJobResponse,
    VideoProgress,
)
from shared.schemas.items import JobItem, JobRequestSpec
from shared.schemas.result import JobResult
from shared.settings import Settings, require

logger = logging.getLogger(__name__)

TOKEN_HEADER = "x-guest-access-token"
JOB_ID_NAMESPACE = b"tripvlog-job:"


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    starter: JobStarter
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def job_id_for(request_id: uuid.UUID) -> uuid.UUID:
    """requestId → jobId. 같은 요청은 같은 작업이 된다. 형식은 UUID v4."""
    digest = hashlib.sha256(JOB_ID_NAMESPACE + request_id.bytes).digest()
    return uuid.UUID(bytes=digest[:16], version=4)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _response(status: int, body: BaseModel) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": body.model_dump_json(exclude_none=True),
    }


def _error(status: int, code: str, message: str, job_id: uuid.UUID | None = None) -> dict[str, Any]:
    return _response(
        status, ErrorResponse(error=ErrorBody(code=code, message=message), job_id=job_id)
    )


def _not_found() -> dict[str, Any]:
    return _error(404, "NOT_FOUND", "job not found")


def create_job(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    try:
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        req = CreateJobRequest.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        # 입력값을 그대로 돌려주지 않는다
        return _error(400, "INVALID_REQUEST", "request body is invalid")

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
    if not deps.repos.jobs.create(job):
        return _error(409, "DUPLICATE_REQUEST", "request already accepted", job_id=job_id)

    try:
        arn = deps.starter.start(str(job_id))
    except Exception:
        logger.exception("failed to start analysis")
        deps.repos.jobs.mutate(
            str(job_id), lambda j: j.model_copy(update={"status": "FAILED"}), deps.clock()
        )
        return _error(503, "START_FAILED", "could not start analysis")
    deps.repos.jobs.mutate(
        str(job_id), lambda j: j.model_copy(update={"execution_arn": arn}), deps.clock()
    )
    return _response(
        202, CreateJobResponse(job_id=job_id, guest_access_token=token, status="QUEUED")
    )


def get_job(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    raw_id = (event.get("pathParameters") or {}).get("jobId", "")
    token = (event.get("headers") or {}).get(TOKEN_HEADER)
    try:
        job_id = str(uuid.UUID(raw_id))
    except (ValueError, TypeError, AttributeError):
        return _not_found()
    if not token:
        return _not_found()
    job = deps.repos.jobs.get(job_id)
    if job is None or job.guest_access_hash is None:
        return _not_found()
    if not hmac.compare_digest(hash_token(token), job.guest_access_hash):
        return _not_found()

    result = None
    if job.status in TERMINAL_STATUSES and job.result_s3_key:
        result = deps.repos.blobs.get_model(job.result_s3_key, JobResult)
    return _response(
        200,
        GetJobResponse(
            job_id=job.job_id,
            status=job.status,
            progress=job.progress,
            videos=[VideoProgress(video_id=r.video_id, state=r.state) for r in job.video_refs],
            result=result,
        ),
    )


ROUTES: dict[str, Callable[[dict[str, Any], Deps], dict[str, Any]]] = {
    "POST /public/jobs": create_job,
    "GET /public/jobs/{jobId}": get_job,
}


def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return _error(404, "NOT_FOUND", "route not found")
    try:
        return route(event, deps)
    except Exception:
        logger.exception("unhandled error")
        return _error(500, "INTERNAL", "internal error")


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

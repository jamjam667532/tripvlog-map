"""[0] 작업 API 공통 부분 (api_public 게스트, api_jobs 로그인). HTTP API 페이로드 2.0.

두 경로는 사용자를 정하는 방식(게스트 토큰 / JWT sub)만 다르고,
작업 만들기·실행 시작·조회 응답은 같다.
"""

import base64
import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from shared.clients.orchestrator import JobStarter
from shared.repos import BlobStore, Repos
from shared.schemas.api import (
    TERMINAL_STATUSES,
    ErrorBody,
    ErrorResponse,
    GetJobResponse,
    VideoProgress,
)
from shared.schemas.items import JobItem
from shared.schemas.result import JobResult

logger = logging.getLogger(__name__)

JOB_ID_NAMESPACE = b"tripvlog-job:"
USER_PREFIX = "google:"  # 로그인 사용자 ID = google:<Google ID 토큰 sub> (결정 0007-2)


def job_id_for(request_id: uuid.UUID) -> uuid.UUID:
    """requestId → jobId. 같은 요청은 같은 작업이 된다. 형식은 UUID v4."""
    digest = hashlib.sha256(JOB_ID_NAMESPACE + request_id.bytes).digest()
    return uuid.UUID(bytes=digest[:16], version=4)


def response(status: int, body: BaseModel) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": body.model_dump_json(exclude_none=True),
    }


def error(status: int, code: str, message: str, job_id: uuid.UUID | None = None) -> dict[str, Any]:
    return response(
        status, ErrorResponse(error=ErrorBody(code=code, message=message), job_id=job_id)
    )


def not_found() -> dict[str, Any]:
    return error(404, "NOT_FOUND", "job not found")


def json_body(event: dict[str, Any]) -> Any:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    return json.loads(raw)


def path_job_id(event: dict[str, Any]) -> str | None:
    raw = (event.get("pathParameters") or {}).get("jobId", "")
    try:
        return str(uuid.UUID(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def start_job(
    job: JobItem, repos: Repos, starter: JobStarter, clock: Callable[[], datetime]
) -> dict[str, Any] | None:
    """작업을 저장하고 실행을 시작한다. 성공하면 None, 실패하면 돌려줄 오류 응답."""
    if not repos.jobs.create(job):
        return error(409, "DUPLICATE_REQUEST", "request already accepted", job_id=job.job_id)
    job_id = str(job.job_id)
    try:
        arn = starter.start(job_id)
    except Exception:
        logger.exception("failed to start analysis")
        repos.jobs.mutate(job_id, lambda j: j.model_copy(update={"status": "FAILED"}), clock())
        return error(503, "START_FAILED", "could not start analysis")
    repos.jobs.mutate(job_id, lambda j: j.model_copy(update={"execution_arn": arn}), clock())
    return None


def job_view(job: JobItem, blobs: BlobStore) -> GetJobResponse:
    """조회 응답. 종료 상태면 최종 결과, 진행 중이면 끝난 영상만으로 만든 중간 결과."""
    result, stage = None, None
    if job.status in TERMINAL_STATUSES and job.result_s3_key:
        result, stage = blobs.get_model(job.result_s3_key, JobResult), "FINAL"
    elif job.status not in TERMINAL_STATUSES and job.live_result_s3_key:
        result = blobs.get_model(job.live_result_s3_key, JobResult)
        stage = "PARTIAL_LIVE"
    return GetJobResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        videos=[VideoProgress(video_id=r.video_id, state=r.state) for r in job.video_refs],
        result=result,
        result_stage=stage,
    )


class Unauthorized(Exception):
    pass


def user_id_of(event: dict[str, Any]) -> str:
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get(
        "claims"
    ) or {}
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise Unauthorized
    return USER_PREFIX + sub

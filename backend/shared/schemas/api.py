"""API 요청·응답 (spec §3). 오류 형식은 {"error": {"code", "message"}}."""

from typing import Annotated, Literal

from pydantic import UUID4, Field, StringConstraints, field_validator

from shared.schemas.base import CamelModel
from shared.schemas.common import ChannelId, Companion, Style, VideoId
from shared.schemas.result import JobResult

JobStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED"]
# 결정 0002-2: 분석 전 PENDING, 분석 중 ANALYZING
VideoState = Literal["PENDING", "ANALYZING", "DONE", "FAILED", "SKIPPED"]
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset({"SUCCEEDED", "PARTIAL", "FAILED"})

MAX_STYLES = 3

Destination = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
# secrets.token_urlsafe(32) 결과: base64url 43자
GuestAccessToken = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]


def _unique_styles(value: list[Style]) -> list[Style]:
    if len(set(value)) != len(value):
        raise ValueError("styles must not contain duplicates")
    return value


class Preferences(CamelModel):
    styles: Annotated[list[Style], Field(max_length=MAX_STYLES)] = Field(default_factory=list)
    companion: Companion | None = None

    _unique = field_validator("styles", mode="after")(_unique_styles)


class CreateJobRequest(Preferences):
    """POST /public/jobs, POST /jobs 본문. userId는 받지 않는다(JWT sub로만 결정)."""

    request_id: UUID4
    destination: Destination


class CreateJobResponse(CamelModel):
    job_id: UUID4
    guest_access_token: GuestAccessToken | None = None  # 비로그인 생성 응답에서만 한 번 반환
    status: JobStatus


class Progress(CamelModel):
    total: Annotated[int, Field(ge=0)] = 0
    analyzed: Annotated[int, Field(ge=0)] = 0
    failed: Annotated[int, Field(ge=0)] = 0


class VideoProgress(CamelModel):
    """진행 화면의 영상별 상태. 제목·채널명은 결정 0008-2-3으로 추가 예정."""

    video_id: VideoId
    state: VideoState


class GetJobResponse(CamelModel):
    job_id: UUID4
    status: JobStatus
    progress: Progress
    videos: list[VideoProgress] = Field(default_factory=list)
    result: JobResult | None = None


class RerankRequest(Preferences):
    """POST /jobs/{jobId}/rerank. 규칙으로 순위만 다시 계산한다."""


class UpdatePreferencesRequest(CamelModel):
    """PATCH /me/preferences. 보낸 필드만 바꾼다."""

    styles: Annotated[list[Style], Field(max_length=MAX_STYLES)] | None = None
    companion: Companion | None = None
    reference_channel_ids: list[ChannelId] | None = None

    @field_validator("styles", mode="after")
    @classmethod
    def _unique(cls, value: list[Style] | None) -> list[Style] | None:
        return None if value is None else _unique_styles(value)


class ErrorBody(CamelModel):
    code: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
    message: str


class ErrorResponse(CamelModel):
    error: ErrorBody
    job_id: UUID4 | None = None  # 409 DUPLICATE_REQUEST일 때 기존 jobId

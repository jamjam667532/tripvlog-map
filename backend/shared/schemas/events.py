"""[0]~[4] Step Functions 단계 사이의 이벤트 계약. ID·상태·S3 키만 넘긴다(256 KiB 제한).

흐름 (결정 0004):
  collect → Map(videoRefs){ claim ─ANALYZE→ observe → interpret → match
                                  ─REUSE─→ (끝)
                                  ─WAIT──→ Wait 30초 → claim }
            Map 항목 Catch → claim(action=fail)
  → aggregate(action=replace) ─대체 있음→ 같은 영상 흐름 → aggregate(action=replace) …
                              ─없음────→ aggregate(action=aggregate)

앞 단계 출력이 그대로 다음 단계 입력이 되므로 모르는 키는 무시한다.
"""

from typing import Annotated, Any, Literal

from pydantic import UUID4, ConfigDict, Field

from shared.schemas.api import JobStatus
from shared.schemas.base import CamelModel
from shared.schemas.common import ChannelId, NonEmptyStr, VideoId

ClaimDecision = Literal["ANALYZE", "REUSE", "WAIT"]


class EventModel(CamelModel):
    model_config = ConfigDict(extra="ignore")


class JobInput(EventModel):
    """collect 입력. api가 StartExecution에 넘긴다."""

    job_id: UUID4


class VideoTask(EventModel):
    """Map 항목. 영상 하나의 분석 단위."""

    job_id: UUID4
    video_id: VideoId
    channel_id: ChannelId
    analysis_version: NonEmptyStr

    def task_fields(self) -> dict[str, Any]:
        """다음 단계 이벤트를 만들 때 쓰는 공통 필드."""
        return {name: getattr(self, name) for name in VideoTask.model_fields}


class CollectOutput(EventModel):
    job_id: UUID4
    video_refs: list[VideoTask]


class ClaimInput(VideoTask):
    action: Literal["claim"] = "claim"
    wait_count: Annotated[int, Field(ge=0)] = 0


class ClaimOutput(VideoTask):
    decision: ClaimDecision
    wait_count: Annotated[int, Field(ge=0)] = 0


class StepError(EventModel):
    """Step Functions Catch의 ResultPath 값. Cause는 원문이 들어 있을 수 있어 저장하지 않는다."""

    model_config = ConfigDict(alias_generator=None)

    Error: str = "Unknown"
    Cause: str | None = None


class FailInput(VideoTask):
    action: Literal["fail"]
    error: StepError = Field(default_factory=StepError)


class FailOutput(VideoTask):
    state: Literal["FAILED"] = "FAILED"


class ObserveOutput(VideoTask):
    observation_s3_key: NonEmptyStr


class InterpretOutput(ObserveOutput):
    interpretation_s3_key: NonEmptyStr


class MatchOutput(VideoTask):
    state: Literal["DONE"] = "DONE"


class AggregateInput(EventModel):
    job_id: UUID4
    action: Literal["replace", "aggregate"] = "aggregate"


class ReplaceOutput(EventModel):
    job_id: UUID4
    replacement: VideoTask | None = None


class AggregateOutput(EventModel):
    job_id: UUID4
    status: JobStatus
    result_s3_key: str | None = None

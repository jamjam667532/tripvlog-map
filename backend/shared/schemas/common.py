"""여러 스키마가 함께 쓰는 값 타입과 작은 모델."""

from typing import Annotated, Any, Literal, get_args

from pydantic import Field, StringConstraints, field_validator, model_validator

from shared.schemas.base import CamelModel

Style = Literal["맛집", "카페·포토스팟", "관광·역사", "쇼핑", "가성비"]
Companion = Literal["혼자", "커플", "친구", "가족"]
Category = Literal["RESTAURANT", "CAFE", "ATTRACTION", "OTHER"]
VisitStatus = Literal["VISITED", "MENTIONED", "UNCLEAR"]
MatchStatus = Literal["CONFIRMED", "UNCONFIRMED"]
ClueType = Literal["SPEECH", "SCREEN_TEXT", "SCENE"]
RatingValue = Literal["POSITIVE", "NEGATIVE", "MIXED", "NONE", "UNDETERMINED"]
RatingAspect = Literal["taste", "price", "wait", "service"]
TimeEvidenceKind = Literal["SCENE", "STATED_TIME", "WAIT_EXPERIENCE", "CREATOR_TIP"]
Situation = Literal[
    "OPENING", "MORNING", "LUNCH_PEAK", "AFTERNOON", "EVENING", "NIGHT", "SUNSET", "OTHER"
]

_RATING_VALUES: frozenset[str] = frozenset(get_args(RatingValue))
_CLOCK_KEYS = ("localClockTime", "local_clock_time")

EVIDENCE_TEXT_MAX = 200

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
VideoId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ChannelId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ClockTime = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
EpochSeconds = Annotated[int, Field(ge=0)]


def truncate_evidence(value: Any) -> Any:
    """근거 원문은 최대 200자. 넘치면 자른다(원문 인용이므로 버리지 않는다)."""
    if isinstance(value, str):
        return value.strip()[:EVIDENCE_TEXT_MAX]
    return value


class Ratings(CamelModel):
    """항목별 평가. 값이 없으면 NONE(근거 없음), 열거형 밖의 값은 UNDETERMINED로 바꾼다."""

    overall: RatingValue = "NONE"
    taste: RatingValue = "NONE"
    price: RatingValue = "NONE"
    wait: RatingValue = "NONE"
    service: RatingValue = "NONE"

    @field_validator("*", mode="before")
    @classmethod
    def _unknown_to_undetermined(cls, value: Any) -> Any:
        if value is None:
            return "NONE"
        if value not in _RATING_VALUES:
            return "UNDETERMINED"
        return value


class TimeEvidence(CamelModel):
    """방문 시간대 근거. localClockTime은 STATED_TIME일 때만 남긴다.

    Bedrock 출력(snake_case)과 DynamoDB 아이템(camelCase) 양쪽에서 쓰므로 두 표기를 모두 받는다.
    """

    kind: TimeEvidenceKind
    situation: Situation
    local_clock_time: ClockTime | None = None
    evidence_text: NonEmptyStr

    _truncate = field_validator("evidence_text", mode="before")(truncate_evidence)

    @model_validator(mode="before")
    @classmethod
    def _clock_only_for_stated_time(cls, data: Any) -> Any:
        # 형식 검증 전에 지운다: STATED_TIME이 아니면 어떤 값이 와도 null.
        if isinstance(data, dict) and data.get("kind") != "STATED_TIME":
            data = {k: v for k, v in data.items() if k not in _CLOCK_KEYS}
        return data


class VideoTimeRange(CamelModel):
    """영상 재생 위치(초). 방문 시각이 아니다."""

    start_sec: Annotated[int, Field(ge=0)]
    end_sec: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _ordered(self) -> "VideoTimeRange":
        if self.end_sec < self.start_sec:
            raise ValueError("endSec must be >= startSec")
        return self

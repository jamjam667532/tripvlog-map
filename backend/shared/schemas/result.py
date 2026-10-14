"""결과 JSON (spec §6.4). aggregate가 만들고 API가 반환한다."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from shared.schemas.base import CamelModel
from shared.schemas.common import (
    Category,
    ChannelId,
    MatchStatus,
    NonEmptyStr,
    RatingAspect,
    Situation,
    TimeEvidenceKind,
    VideoId,
    truncate_evidence,
)

NonNegative = Annotated[int, Field(ge=0)]


class ChannelCount(CamelModel):
    visited: NonNegative
    denominator: NonNegative  # 분석 성공 채널 수

    @model_validator(mode="after")
    def _within_denominator(self) -> "ChannelCount":
        if self.visited > self.denominator:
            raise ValueError("visited must be <= denominator")
        return self


class RatingCount(CamelModel):
    positive: NonNegative = 0
    negative: NonNegative = 0
    mixed: NonNegative = 0


class TimeEvidenceSummary(CamelModel):
    kind: TimeEvidenceKind
    situation: Situation
    channels: Annotated[int, Field(ge=1)]
    recommend: bool = False


class EvidenceLink(CamelModel):
    channel_id: ChannelId
    video_id: VideoId
    start_sec: NonNegative  # 영상 재생 위치. 링크: https://youtu.be/{videoId}?t={startSec}
    text: Annotated[str, Field(max_length=200)]

    @model_validator(mode="before")
    @classmethod
    def _truncate_text(cls, data: object) -> object:
        if isinstance(data, dict) and "text" in data:
            data = {**data, "text": truncate_evidence(data["text"])}
        return data


class ResultPlace(CamelModel):
    place_id: NonEmptyStr
    name: NonEmptyStr
    category: Category
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
    area_group: str | None = None
    rank: Annotated[int, Field(ge=1)]
    match_status: MatchStatus
    channels: ChannelCount
    ratings: dict[RatingAspect, RatingCount] = Field(default_factory=dict)
    time_evidence: list[TimeEvidenceSummary] = Field(default_factory=list)
    evidence: list[EvidenceLink] = Field(default_factory=list)


class UnconfirmedPlace(CamelModel):
    names: Annotated[list[NonEmptyStr], Field(min_length=1)]
    reason: Literal["MULTIPLE_BRANCHES"]


class JobResult(CamelModel):
    job_id: NonEmptyStr
    destination: NonEmptyStr
    analyzed_channels: NonNegative
    failed_videos: NonNegative
    places: list[ResultPlace] = Field(default_factory=list)
    unconfirmed: list[UnconfirmedPlace] = Field(default_factory=list)

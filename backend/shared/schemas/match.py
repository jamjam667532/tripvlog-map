"""영상별 매칭 요약 (결정 0004-3). S3 analysis/{videoId}/{version}/match.json.

match가 쓰고 aggregate가 읽는다. 분석을 재사용하는 작업도 같은 요약을 쓴다.
Google 응답의 이름·주소는 두지 않는다. 이름은 영상 기반 표기, 장소는 ID만.
"""

from typing import Annotated, Literal

from pydantic import Field

from shared.schemas.base import CamelModel
from shared.schemas.common import Category, NonEmptyStr, VideoId


class ConfirmedMatch(CamelModel):
    place_id: NonEmptyStr
    # 영상 이름 + branch_hint (예: "이치란 · 도톤보리"). 결정 0002-4
    name: NonEmptyStr
    category: Category


class UnconfirmedMatch(CamelModel):
    names: Annotated[list[NonEmptyStr], Field(min_length=1)]
    place_ids: Annotated[list[NonEmptyStr], Field(min_length=2)]
    reason: Literal["MULTIPLE_BRANCHES"] = "MULTIPLE_BRANCHES"


class MatchSummary(CamelModel):
    video_id: VideoId
    analysis_version: NonEmptyStr
    confirmed: list[ConfirmedMatch] = Field(default_factory=list)
    unconfirmed: list[UnconfirmedMatch] = Field(default_factory=list)
    discarded: Annotated[int, Field(ge=0)] = 0

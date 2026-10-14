"""Gemini 관찰 결과 (spec §5.2). Gemini는 관찰만 한다: 들린 말, 보인 글자, 장면."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from shared.schemas.base import AIModel
from shared.schemas.common import ClueType, VideoId

Uncertainty = Literal["INAUDIBLE", "TEXT_UNCLEAR", "TARGET_AMBIGUOUS"]


class Clue(AIModel):
    start_sec: Annotated[int, Field(ge=0)]
    end_sec: Annotated[int, Field(ge=0)]
    clue_type: ClueType
    heard_name: str | None = None  # 들린 장소명 원문
    seen_text: str | None = None  # 간판·자막·메뉴판에서 읽은 글자
    utterance: str | None = None  # 장소 주변 발화·편집 자막 원문 (평가·시간 근거)
    scene: str | None = None  # 방문을 보여주는 장면 한 줄
    scene_daypart: Literal["DAY", "NIGHT", "UNKNOWN"] = "UNKNOWN"
    uncertainty: list[Uncertainty] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ordered(self) -> "Clue":
        if self.end_sec < self.start_sec:
            raise ValueError("end_sec must be >= start_sec")
        return self


class ObservationResult(AIModel):
    video_id: VideoId
    clues: list[Clue]

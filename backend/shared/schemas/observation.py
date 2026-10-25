"""[2-2] Gemini 관찰 결과 (spec §5.2). Gemini는 관찰만 한다: 들린 말, 보인 글자, 장면."""

import re
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


# --- Gemini가 실제로 쓰는 출력 형식 (결정 0006-1) ---
# 정수 초로 받으면 15:51을 1551로 붙여 쓰는 일이 잦아,
# 재생 위치를 "MM:SS" 문자열로 받고 코드에서 초로 바꾼다.

_TIMESTAMP = re.compile(r"^(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)$")


def timestamp_to_sec(value: str) -> int | None:
    """ "MM:SS" 또는 "H:MM:SS" → 초. 형식이 다르면 None."""
    m = _TIMESTAMP.match(value.strip())
    if not m:
        return None
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


class ClueWire(AIModel):
    start: str
    end: str
    clue_type: ClueType
    heard_name: str | None = None
    seen_text: str | None = None
    utterance: str | None = None
    scene: str | None = None
    scene_daypart: Literal["DAY", "NIGHT", "UNKNOWN"] = "UNKNOWN"
    uncertainty: list[Uncertainty] = Field(default_factory=list)


class ObservationWire(AIModel):
    video_id: str
    clues: list[ClueWire]

    def to_result(self, video_id: str, *, max_sec: int | None = None) -> ObservationResult:
        """초 단위 ObservationResult로. 형식이 틀리거나 max_sec(영상 길이)를 넘는 재생 위치가
        하나라도 있으면 잘못된 출력으로 본다(ValueError)."""
        clues: list[Clue] = []
        for c in self.clues:
            start, end = timestamp_to_sec(c.start), timestamp_to_sec(c.end)
            if start is None or end is None:
                raise ValueError(f"bad timestamp: {c.start!r}-{c.end!r}")
            if max_sec is not None and max(start, end) > max_sec:
                raise ValueError(f"timestamp beyond video length: {c.end!r} > {max_sec}s")
            fields = c.model_dump(exclude={"start", "end"})
            clues.append(Clue(start_sec=start, end_sec=max(start, end), **fields))
        return ObservationResult(video_id=video_id, clues=clues)

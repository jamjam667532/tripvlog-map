"""Bedrock 해석 결과 (spec §5.3). Bedrock은 해석만 하고, 확정·집계는 규칙 코드가 한다."""

from typing import Annotated, Any

from pydantic import Field, field_validator

from shared.schemas.base import AIModel
from shared.schemas.common import Category, NonEmptyStr, Ratings, TimeEvidence, VideoId, VisitStatus
from shared.schemas.observation import ObservationResult

MAX_SEARCH_QUERIES = 3


class PlaceCandidate(AIModel):
    candidate_id: NonEmptyStr
    names: Annotated[list[NonEmptyStr], Field(min_length=1)]  # 원문 표기 유지
    branch_hint: str | None = None  # 근거 없으면 None
    search_queries: list[NonEmptyStr] = Field(default_factory=list)
    category: Category
    visit_status: VisitStatus
    clue_refs: list[int]  # ObservationResult.clues 인덱스
    ratings: Ratings = Field(default_factory=Ratings)
    time_evidence: list[TimeEvidence] = Field(default_factory=list)

    @field_validator("search_queries", mode="after")
    @classmethod
    def _cap_queries(cls, value: list[str]) -> list[str]:
        return value[:MAX_SEARCH_QUERIES]

    @field_validator("clue_refs", mode="after")
    @classmethod
    def _dedupe_refs(cls, value: list[int]) -> list[int]:
        return list(dict.fromkeys(value))

    @field_validator("branch_hint", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class InterpretationResult(AIModel):
    video_id: VideoId
    analysis_version: NonEmptyStr
    candidates: list[PlaceCandidate]

    @field_validator("candidates", mode="after")
    @classmethod
    def _drop_unlinked(cls, value: list[PlaceCandidate]) -> list[PlaceCandidate]:
        # 근거(clue_refs)가 없는 후보는 버린다.
        return [c for c in value if c.clue_refs]


def link_to_observation(
    result: InterpretationResult, observation: ObservationResult
) -> InterpretationResult:
    """clue_refs가 관찰 결과 범위를 벗어난 후보를 버린다. 영상이 다르면 오류."""
    if result.video_id != observation.video_id:
        raise ValueError("interpretation and observation refer to different videos")
    n = len(observation.clues)
    kept = [c for c in result.candidates if all(0 <= i < n for i in c.clue_refs)]
    return result.model_copy(update={"candidates": kept})

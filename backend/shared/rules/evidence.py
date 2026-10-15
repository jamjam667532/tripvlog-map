"""해석 후보 → 근거 아이템 값 (결정 0004-7). 관찰 단서에서 그대로 가져오고 새로 만들지 않는다.

- 재생 구간: clue_refs 단서들의 최소 start ~ 최대 end (영상 재생 위치이지 방문 시각이 아니다)
- 근거 문장: utterance → seen_text → heard_name → scene 순으로 처음 나오는 값
- 표시 이름: 영상 표기 + branch_hint (예: "이치란 · 도톤보리", 결정 0002-4)
"""

from collections.abc import Sequence
from dataclasses import dataclass

from shared.schemas.common import ClueType
from shared.schemas.observation import Clue

TEXT_FIELDS = ("utterance", "seen_text", "heard_name", "scene")


@dataclass(frozen=True)
class EvidenceSpan:
    start_sec: int
    end_sec: int
    clue_types: list[ClueType]
    text: str


def evidence_span(clues: Sequence[Clue], refs: Sequence[int]) -> EvidenceSpan:
    picked = [clues[i] for i in refs if 0 <= i < len(clues)]
    if not picked:
        raise ValueError("candidate has no clue in range")
    text = next(
        (
            value.strip()
            for field in TEXT_FIELDS
            for clue in picked
            if (value := getattr(clue, field)) and value.strip()
        ),
        "",
    )
    return EvidenceSpan(
        start_sec=min(c.start_sec for c in picked),
        end_sec=max(c.end_sec for c in picked),
        clue_types=list(dict.fromkeys(c.clue_type for c in picked)),
        text=text,
    )


def display_name(names: Sequence[str], branch_hint: str | None) -> str:
    name = names[0].strip()
    hint = (branch_hint or "").strip()
    if not hint or hint in name:
        return name
    return f"{name} · {hint}"

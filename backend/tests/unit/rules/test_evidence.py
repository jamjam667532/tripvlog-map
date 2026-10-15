import pytest

from shared.rules.evidence import display_name, evidence_span
from shared.schemas.observation import Clue


def clue(start: int, end: int, kind: str = "SPEECH", **kw: object) -> Clue:
    return Clue.model_validate({"start_sec": start, "end_sec": end, "clue_type": kind, **kw})


CLUES = [
    clue(750, 905, heard_name="이치란", utterance="국물 진짜 맛있는데"),
    clue(760, 770, "SCREEN_TEXT", seen_text="一蘭 道頓堀店", scene="가게 간판"),
    clue(1200, 1230, "SCENE", scene="야경"),
]


def test_span_covers_referenced_clues() -> None:
    span = evidence_span(CLUES, [1, 0])
    assert (span.start_sec, span.end_sec) == (750, 905)
    assert span.clue_types == ["SCREEN_TEXT", "SPEECH"]
    assert span.text == "국물 진짜 맛있는데"  # 발화가 간판 글자보다 먼저


def test_span_text_falls_back_in_order() -> None:
    assert evidence_span(CLUES, [1]).text == "一蘭 道頓堀店"
    assert evidence_span(CLUES, [2]).text == "야경"
    assert evidence_span([clue(0, 1)], [0]).text == ""


def test_span_rejects_out_of_range_only() -> None:
    with pytest.raises(ValueError):
        evidence_span(CLUES, [9])


def test_display_name() -> None:
    assert display_name(["이치란", "一蘭"], "도톤보리") == "이치란 · 도톤보리"
    assert display_name(["이치란"], None) == "이치란"
    assert display_name(["이치란 도톤보리점"], "도톤보리") == "이치란 도톤보리점"

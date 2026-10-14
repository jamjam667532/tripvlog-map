import json

from shared.clients.ai_schema import ai_json_schema
from shared.clients.prompts import load_prompt
from shared.schemas.interpretation import InterpretationResult
from shared.schemas.observation import ObservationResult


def test_schema_is_flat_and_structural_only() -> None:
    for model in (ObservationResult, InterpretationResult):
        text = json.dumps(ai_json_schema(model))
        for banned in ('"$ref"', '"$defs"', '"pattern"', '"minLength"', '"default"', '"title"'):
            assert banned not in text, (model.__name__, banned)


def test_all_fields_required_and_closed() -> None:
    schema = ai_json_schema(InterpretationResult)
    cand = schema["properties"]["candidates"]["items"]
    assert cand["additionalProperties"] is False
    assert set(cand["required"]) == set(cand["properties"])
    kinds = cand["properties"]["time_evidence"]["items"]["properties"]["kind"]["enum"]
    assert kinds == ["SCENE", "STATED_TIME", "WAIT_EXPERIENCE", "CREATOR_TIP"]


def test_prompts_carry_core_rules() -> None:
    observe, interpret = load_prompt("observe"), load_prompt("interpret")
    assert "추측" in observe and "원문" in observe
    assert "clue_refs" in interpret and "STATED_TIME" in interpret
    assert "재생 위치" in interpret  # 재생 위치를 방문 시각으로 쓰지 않기

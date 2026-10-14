"""Pydantic 모델 → AI 구조화 출력용 JSON Schema.

모델마다 지원하는 JSON Schema 키워드가 다르므로 형식 제약(길이·패턴·범위)은 빼고 구조만 넘긴다.
빠진 제약은 응답을 받은 뒤 같은 Pydantic 모델로 검증한다.
"""

from typing import Any

from pydantic import BaseModel

_DROP = frozenset(
    {
        "title",
        "default",
        "pattern",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "format",
    }
)


def ai_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """$ref를 펼친 단일 스키마. 모든 필드를 required로 두고 값이 없으면 null을 쓰게 한다."""
    schema = model.model_json_schema(by_alias=False)
    defs = schema.pop("$defs", {})
    return _strip(_inline(schema, defs))  # type: ignore[no-any-return]


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            return _inline(defs[ref.rsplit("/", 1)[-1]], defs)
        return {k: _inline(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        out = {k: _strip(v) for k, v in node.items() if k not in _DROP}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = sorted(out["properties"])
        return out
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node

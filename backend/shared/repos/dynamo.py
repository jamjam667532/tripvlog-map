"""DynamoDB 공통 도우미. 아이템은 항상 Pydantic 모델을 거쳐 쓰고 읽는다."""

import json
from collections.abc import Iterator, Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError
from pydantic import BaseModel

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource

BATCH_GET_MAX = 100
MAX_UNPROCESSED_ROUNDS = 5


def to_item(model: BaseModel) -> dict[str, Any]:
    """모델 → DynamoDB 아이템. None은 빼고, 실수는 Decimal로 바꾼다(boto3는 float를 받지 않는다)."""
    data: dict[str, Any] = json.loads(
        model.model_dump_json(by_alias=True, exclude_none=True), parse_float=Decimal
    )
    return data


def from_item(value: Any) -> Any:
    """DynamoDB 값(Decimal) → JSON 값(int/float)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, Mapping):
        return {k: from_item(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [from_item(v) for v in value]
    return value


def is_conditional_failure(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def _chunks(seq: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def batch_get(
    resource: "DynamoDBServiceResource", table_name: str, keys: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """여러 키를 한 번에 읽는다. 100개씩 나누고 미처리 키는 다시 요청한다."""
    found: list[dict[str, Any]] = []
    for chunk in _chunks(list(keys), BATCH_GET_MAX):
        request: dict[str, Any] = {table_name: {"Keys": list(chunk), "ConsistentRead": True}}
        for _ in range(MAX_UNPROCESSED_ROUNDS):
            resp = resource.batch_get_item(RequestItems=request)
            found.extend(resp.get("Responses", {}).get(table_name, []))
            unprocessed = resp.get("UnprocessedKeys") or {}
            if not unprocessed:
                break
            request = dict(unprocessed)
        else:
            raise RuntimeError("batch_get_item left unprocessed keys")
    return [from_item(i) for i in found]

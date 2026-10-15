"""DynamoDB 테이블 정의 (spec §4). 로컬 테이블 생성 스크립트와 통합 테스트가 같은 정의를 쓴다.

M5의 CDK 스택도 이 키 구조와 같아야 한다.
"""

import contextlib
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from shared.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient


def _attrs(*names: str) -> list[dict[str, str]]:
    return [{"AttributeName": n, "AttributeType": "S"} for n in names]


def _keys(pk: str, sk: str | None = None) -> list[dict[str, str]]:
    keys = [{"AttributeName": pk, "KeyType": "HASH"}]
    if sk is not None:
        keys.append({"AttributeName": sk, "KeyType": "RANGE"})
    return keys


def table_definitions(s: Settings) -> list[dict[str, Any]]:
    """CreateTable 인자 목록. 모두 온디맨드. 키 속성은 전부 문자열."""
    on_demand = {"BillingMode": "PAY_PER_REQUEST"}
    return [
        {
            "TableName": s.users_table,
            "KeySchema": _keys("userId"),
            "AttributeDefinitions": _attrs("userId"),
            **on_demand,
        },
        {
            "TableName": s.jobs_table,
            "KeySchema": _keys("jobId"),
            "AttributeDefinitions": _attrs("jobId", "requestId"),
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "requestId-index",
                    "KeySchema": _keys("requestId"),
                    "Projection": {"ProjectionType": "KEYS_ONLY"},
                }
            ],
            **on_demand,
        },
        {
            "TableName": s.youtube_cache_table,
            "KeySchema": _keys("pk", "sk"),
            "AttributeDefinitions": _attrs("pk", "sk"),
            **on_demand,
        },
        {
            "TableName": s.video_analysis_table,
            "KeySchema": _keys("videoId", "analysisVersion"),
            "AttributeDefinitions": _attrs("videoId", "analysisVersion"),
            **on_demand,
        },
        {
            "TableName": s.places_table,
            "KeySchema": _keys("placeId", "sk"),
            "AttributeDefinitions": _attrs("placeId", "sk", "videoId", "evidenceKey"),
            "GlobalSecondaryIndexes": [
                {
                    # PLACE 아이템에는 videoId가 없어 들어가지 않는다(희소 인덱스)
                    "IndexName": "videoId-index",
                    "KeySchema": _keys("videoId", "evidenceKey"),
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            **on_demand,
        },
        {
            "TableName": s.coord_cache_table,
            "KeySchema": _keys("placeId"),
            "AttributeDefinitions": _attrs("placeId"),
            **on_demand,
        },
    ]


# TTL은 보조 수단이다. 만료 삭제는 cleanup이 명시적으로 한다(spec §5.6)
TTL_TABLES = ("youtube_cache_table", "coord_cache_table")


def create_tables(client: "DynamoDBClient", s: Settings) -> list[str]:
    """없는 테이블만 만든다. 만든 테이블 이름을 돌려준다."""
    existing = set(client.list_tables().get("TableNames", []))
    created = []
    for definition in table_definitions(s):
        name = definition["TableName"]
        if name in existing:
            continue
        client.create_table(**definition)
        client.get_waiter("table_exists").wait(TableName=name)
        created.append(name)
    for attr in TTL_TABLES:
        name = getattr(s, attr)
        try:
            client.update_time_to_live(
                TableName=name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "expiresAt"},
            )
        except ClientError as e:
            # 이미 켜져 있거나 로컬 에뮬레이터가 지원하지 않으면 넘어간다
            if e.response.get("Error", {}).get("Code") not in ("ValidationException",):
                raise
    return created


def delete_tables(client: "DynamoDBClient", s: Settings) -> None:
    for definition in table_definitions(s):
        with contextlib.suppress(client.exceptions.ResourceNotFoundException):
            client.delete_table(TableName=definition["TableName"])

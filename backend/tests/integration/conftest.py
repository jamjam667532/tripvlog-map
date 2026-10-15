"""통합 테스트 fixture.

- DynamoDB: 환경 변수 DYNAMODB_ENDPOINT가 있으면 DynamoDB Local(make local, CI 서비스),
  없으면 moto로 대신한다. 테스트마다 테이블 이름에 접두사를 붙여 서로 섞이지 않게 한다.
- S3·SSM: 항상 moto.
- 외부 API(YouTube, Gemini, Bedrock, Places)는 tests.fakes를 쓴다. 실제 호출 금지.
"""

import os
import uuid
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import boto3
import pytest
from moto import mock_aws

from shared.repos import Repos
from shared.repos.tables import create_tables, delete_tables
from shared.settings import Settings

REGION = "us-east-1"


@pytest.fixture
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
        "AWS_REGION": REGION,
    }.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def settings() -> Settings:
    prefix = f"t{uuid.uuid4().hex[:8]}-"
    base = Settings()
    return replace(
        base,
        jobs_table=prefix + base.jobs_table,
        users_table=prefix + base.users_table,
        youtube_cache_table=prefix + base.youtube_cache_table,
        video_analysis_table=prefix + base.video_analysis_table,
        places_table=prefix + base.places_table,
        coord_cache_table=prefix + base.coord_cache_table,
        bucket=f"tripvlog-test-{prefix.rstrip('-')}",
        dynamodb_endpoint=os.environ.get("DYNAMODB_ENDPOINT") or None,
    )


@pytest.fixture
def aws(aws_env: None, settings: Settings) -> Iterator[tuple[Any, Any]]:
    """(dynamodb resource, s3 client). 테이블 6개와 버킷을 만든다."""
    local = settings.dynamodb_endpoint
    config: Any = {"core": {"passthrough": {"services": ["dynamodb"]}}} if local else None
    with mock_aws(config=config):
        ddb_kwargs: dict[str, Any] = {"region_name": REGION}
        if local:
            ddb_kwargs["endpoint_url"] = local
        client = boto3.client("dynamodb", **ddb_kwargs)
        resource = boto3.resource("dynamodb", **ddb_kwargs)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=settings.bucket)
        create_tables(client, settings)
        try:
            yield resource, s3
        finally:
            if local:
                delete_tables(client, settings)


@pytest.fixture
def repos(aws: tuple[Any, Any], settings: Settings) -> Repos:
    dynamodb, s3 = aws
    return Repos.from_settings(settings, dynamodb=dynamodb, s3=s3)

"""[1][2-2][2-3][2-4] 서버 키 읽기: 설정 버킷의 keys.json (결정 0007-3). 실제 S3는 부르지 않는다."""

import json

import boto3
import pytest
from moto import mock_aws

from shared.clients import secrets
from shared.clients.secrets import SECRET_GEMINI, SECRET_LLM_BASE_URL, get_secret

BUCKET = "sgu-clicktotrip-config"


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "ap-northeast-2",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CONFIG_BUCKET", raising=False)
    monkeypatch.delenv("CONFIG_KEY", raising=False)
    secrets._load_keys.cache_clear()
    with mock_aws():
        yield
    secrets._load_keys.cache_clear()


def _put(body: bytes) -> None:
    s3 = boto3.client("s3")
    s3.create_bucket(
        Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"}
    )
    s3.put_object(Bucket=BUCKET, Key="keys.json", Body=body)


def test_reads_named_key_from_config_bucket() -> None:
    _put(json.dumps({"gemini": "g-value", "llm_base_url": "https://gw.example/v1"}).encode())
    assert get_secret(SECRET_GEMINI) == "g-value"
    assert get_secret(SECRET_LLM_BASE_URL) == "https://gw.example/v1"


def test_reads_file_once_per_process() -> None:
    _put(json.dumps({"gemini": "first"}).encode())
    assert get_secret(SECRET_GEMINI) == "first"
    boto3.client("s3").put_object(Bucket=BUCKET, Key="keys.json", Body=b'{"gemini": "second"}')
    assert get_secret(SECRET_GEMINI) == "first"  # 콜드 스타트에 1회만 읽는다


def test_missing_key_error_names_the_key_not_the_values() -> None:
    _put(json.dumps({"gemini": "super-secret-value"}).encode())
    with pytest.raises(RuntimeError) as e:
        get_secret("youtube")
    assert "youtube" in str(e.value)
    assert "super-secret-value" not in str(e.value)


def test_non_object_file_is_rejected() -> None:
    _put(b'["gemini"]')
    with pytest.raises(RuntimeError):
        get_secret(SECRET_GEMINI)


def test_bucket_and_key_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = boto3.client("s3")
    s3.create_bucket(
        Bucket="other-config", CreateBucketConfiguration={"LocationConstraint": "ap-northeast-2"}
    )
    s3.put_object(Bucket="other-config", Key="k.json", Body=b'{"gemini": "x"}')
    monkeypatch.setenv("CONFIG_BUCKET", "other-config")
    monkeypatch.setenv("CONFIG_KEY", "k.json")
    assert get_secret(SECRET_GEMINI) == "x"

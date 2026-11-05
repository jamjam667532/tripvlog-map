"""[1][2-2][2-3][2-4] 서버 키는 설정 버킷의 keys.json에서 읽고 프로세스 안에서만 캐시한다.

결정 0007-3: SSM Parameter Store는 학교 계정에서 쓸 수 없다. 환경 변수에는 버킷·객체 이름만 있고
값은 없다. 값과 JSON 전체를 로그·예외 메시지에 남기지 않는다(키 이름만).
"""

import json
from functools import lru_cache
from typing import Any

import boto3

from shared.settings import Settings

SECRET_GEMINI = "gemini"
SECRET_YOUTUBE = "youtube"
SECRET_PLACES = "places"
SECRET_LLM_API_KEY = "llm_api_key"
SECRET_LLM_BASE_URL = "llm_base_url"


@lru_cache(maxsize=4)
def _load_keys(bucket: str, key: str) -> dict[str, str]:
    s3: Any = boto3.client("s3")
    data = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    if not isinstance(data, dict):
        raise RuntimeError("keys file must be a JSON object")
    return {str(k): str(v) for k, v in data.items()}


def get_secret(name: str) -> str:
    s = Settings.from_env()
    keys = _load_keys(s.config_bucket, s.config_key)
    if name not in keys:
        raise RuntimeError(f"secret {name!r} is not in the keys file")
    return keys[name]

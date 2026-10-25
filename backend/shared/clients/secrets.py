"""[1][2-2][2-4] 서버 키는 SSM Parameter Store(SecureString)에서 읽고 프로세스 안에서만 캐시한다.

로그 금지.
"""

from functools import lru_cache
from typing import Any

import boto3


@lru_cache(maxsize=16)
def get_secret(parameter_name: str) -> str:
    ssm: Any = boto3.client("ssm")
    value: str = ssm.get_parameter(Name=parameter_name, WithDecryption=True)["Parameter"]["Value"]
    return value

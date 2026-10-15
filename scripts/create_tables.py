"""로컬 DynamoDB(make local)에 테이블 6개를 만든다.

make local                      # 다른 터미널에서
DYNAMODB_ENDPOINT=http://localhost:8000 uv run python scripts/create_tables.py
"""

import os
import sys
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from shared.repos.tables import create_tables
from shared.settings import Settings


def main() -> None:
    settings = Settings.from_env()
    endpoint = settings.dynamodb_endpoint or "http://localhost:8000"
    # DynamoDB Local은 아무 자격 증명이나 받는다
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
    client = boto3.client(
        "dynamodb", endpoint_url=endpoint, region_name=os.environ.get("AWS_REGION", "us-east-1")
    )
    created = create_tables(client, settings)
    print(f"created: {', '.join(created) or '(none, all exist)'}")


if __name__ == "__main__":
    main()

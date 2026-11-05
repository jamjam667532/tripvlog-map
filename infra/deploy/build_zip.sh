#!/usr/bin/env bash
# Lambda 공통 zip 만들기(저장소 루트에서 실행, uv 필요): backend 코드 + 의존성(리눅스용 바이너리).
set -euo pipefail
rm -rf build dist && mkdir -p build dist
uv pip install -q --target build --python-platform x86_64-manylinux2014 --python-version 3.12 \
  --only-binary :all: pydantic google-genai          # boto3는 Lambda에 기본으로 있다
cp -r backend/functions backend/shared build/
find build -name "__pycache__" -prune -exec rm -rf {} +
find build -type d -name tests -prune -exec rm -rf {} +   # 라이브러리 자체 테스트는 필요 없다
(cd build && zip -qr ../dist/backend.zip .)
ls -lh dist/backend.zip

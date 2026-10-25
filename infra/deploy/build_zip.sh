#!/usr/bin/env bash
# [초안] Lambda 공통 zip 만들기: backend 코드 + 의존성(리눅스용 바이너리).
set -euo pipefail
rm -rf build dist && mkdir -p build dist
pip install -q --target build --platform manylinux2014_x86_64 --only-binary=:all: \
  --python-version 3.12 pydantic google-genai          # boto3는 Lambda에 기본으로 있다
cp -r backend/functions backend/shared build/
find build -name "__pycache__" -prune -exec rm -rf {} +
(cd build && zip -qr ../dist/backend.zip .)
ls -lh dist/backend.zip

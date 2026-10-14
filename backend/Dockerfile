# 함수별 Lambda 이미지. 빌드: docker build -f backend/Dockerfile --build-arg FUNCTION=collect .
FROM public.ecr.aws/lambda/python:3.12

ARG FUNCTION
# 베이스 이미지는 출시 시점 릴리스에 고정돼 있으므로 최신 릴리스의 보안 패치를 반영한다 (Trivy HIGH 대응)
RUN dnf -y --releasever=latest upgrade && dnf clean all

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

COPY pyproject.toml uv.lock /tmp/build/
RUN uv export --project /tmp/build --frozen --no-default-groups --no-hashes -o /tmp/build/requirements.txt \
    && uv pip install --no-cache --target "${LAMBDA_TASK_ROOT}" -r /tmp/build/requirements.txt \
    && rm -rf /tmp/build

COPY backend/shared ${LAMBDA_TASK_ROOT}/shared
COPY backend/functions/${FUNCTION}/handler.py ${LAMBDA_TASK_ROOT}/handler.py

CMD ["handler.handler"]

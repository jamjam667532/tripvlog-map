"""로컬 시연 서버 (AWS 배포 전). 실제 YouTube·Gemini·Places·LLM 게이트웨이를 부른다(유료·한도 소모).

- API: api_public 핸들러를 그대로 쓴다(POST /public/jobs, GET /public/jobs/{jobId}).
- 파이프라인: Step Functions 대신 스레드에서 같은 순서로 돌린다. 영상은 동시에(결정 0008 제안).
  영상 하나가 끝날 때마다 aggregate(snapshot)로 중간 결과를 써서 화면이 끝난 영상부터 지도에 그린다.
- 저장: moto(메모리) DynamoDB·S3. 서버를 끄면 사라진다. 켜 둔 동안은 분석한 영상을 재사용한다.
- 키: --env-file의 GEMINI_API_KEY, YOUTUBE_API_KEY, PLACES_API_KEY, LLM_API_KEY, LLM_BASE_URL.
  SSM·S3 설정 버킷을 쓰지 않는다. 키 값은 출력하지 않는다.

  cd backend && uv run python -m local.server --env-file ../experiments/.env
  프론트: frontend/.env.local에 VITE_API_BASE=/api (vite가 /api를 이 서버로 넘긴다)
"""

import argparse
import contextlib
import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from moto import mock_aws

from functions.aggregate import handler as aggregate_fn
from functions.api_public import handler as api_fn
from functions.claim import handler as claim_fn
from functions.collect import handler as collect_fn
from functions.interpret import handler as interpret_fn
from functions.match import handler as match_fn
from functions.observe import handler as observe_fn
from functions.observe.handler import video_duration
from shared.clients.bedrock import BedrockInterpreter, ChunkedInterpreter, GatewayChatInterpreter
from shared.clients.errors import ExternalApiError
from shared.clients.gemini import (
    GeminiObserver,
    GeminiYouTubeObserver,
    Observation,
    RateLimiter,
    SegmentedObserver,
)
from shared.clients.places import PlacesClient, PlacesTextSearch
from shared.clients.youtube import YouTubeClient, YouTubeDataApi
from shared.repos import Repos
from shared.repos.tables import create_tables
from shared.schemas.events import (
    AggregateInput,
    ClaimOutput,
    CollectOutput,
    InterpretOutput,
    JobInput,
    ObserveOutput,
    ReplaceOutput,
    VideoTask,
)
from shared.settings import Settings

logger = logging.getLogger("local")

REGION = "us-east-1"
WAIT_SEC = 5  # 다른 작업이 같은 영상을 분석 중이면 기다렸다 다시 claim (Step Functions Wait 대신)
REQUIRED_KEYS = (
    "GEMINI_API_KEY",
    "YOUTUBE_API_KEY",
    "PLACES_API_KEY",
    "LLM_API_KEY",
    "LLM_BASE_URL",
)


def load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


@dataclass(frozen=True)
class Clients:
    youtube: YouTubeClient
    gemini: GeminiObserver
    places: PlacesClient
    llm: BedrockInterpreter


class ThrottledObserver:
    """Gemini 무료 한도(분당 요청·토큰) 대비: 전역 동시 호출 제한 + 429·503 재시도."""

    RETRY_DELAYS = (10.0, 20.0, 40.0)

    def __init__(self, inner: GeminiObserver, max_concurrent: int) -> None:
        self._inner = inner
        self._gate = threading.Semaphore(max_concurrent)

    def observe(self, video_id: str) -> Observation:
        for delay in (*self.RETRY_DELAYS, None):
            try:
                with self._gate:
                    return self._inner.observe(video_id)
            except ExternalApiError as e:
                if e.status not in (429, 503) or delay is None:
                    raise
                logger.info("video %s: gemini %s, retry in %.0fs", video_id, e.status, delay)
                time.sleep(delay)
        raise AssertionError("unreachable")


def _json(model: Any) -> dict[str, Any]:
    out: dict[str, Any] = model.model_dump(mode="json")
    return out


class LocalPipeline:
    """tests/integration/pipeline.py와 같은 순서. boto3 resource는 스레드 간 공유하지 않는다."""

    def __init__(self, settings: Settings, clients: Clients, concurrency: int) -> None:
        self._s = settings
        self._c = clients
        self._concurrency = concurrency
        self._snapshot_lock = threading.Lock()  # 같은 live.json을 동시에 쓰지 않게

    def _repos(self) -> Repos:
        return Repos.from_settings(self._s)

    def _run_video(self, task: dict[str, Any]) -> None:
        repos = self._repos()
        claim = claim_fn.Deps(self._s, repos)
        vid = task["videoId"]
        try:
            state = task
            while True:
                claimed = claim_fn.run(state, claim)
                assert isinstance(claimed, ClaimOutput)
                if claimed.decision == "REUSE":
                    logger.info("video %s: reuse", vid)
                    return
                if claimed.decision == "ANALYZE":
                    break
                time.sleep(WAIT_SEC)
                state = _json(claimed)
            t0 = time.monotonic()
            observed = observe_fn.run(
                VideoTask.model_validate(_json(claimed)),
                observe_fn.Deps(self._s, repos, self._c.gemini),
            )
            t1 = time.monotonic()
            interpreted = interpret_fn.run(
                ObserveOutput.model_validate(_json(observed)),
                interpret_fn.Deps(self._s, repos, self._c.llm),
            )
            t2 = time.monotonic()
            match_fn.run(
                InterpretOutput.model_validate(_json(interpreted)),
                match_fn.Deps(self._s, repos, self._c.places),
            )
            logger.info(
                "video %s: observe %.0fs, interpret %.0fs, match %.0fs",
                vid,
                t1 - t0,
                t2 - t1,
                time.monotonic() - t2,
            )
        except Exception as e:
            logger.warning("video %s failed: %s", vid, e)
            error = {"Error": type(e).__name__, "Cause": str(e)}
            claim_fn.run({**task, "action": "fail", "error": error}, claim)

    def _video_then_snapshot(self, task: dict[str, Any]) -> None:
        """영상 하나가 끝나면(성공·실패 모두) 지금까지 결과를 live.json으로 내보낸다."""
        self._run_video(task)
        try:
            with self._snapshot_lock:
                aggregate_fn.run(
                    AggregateInput.model_validate({"jobId": task["jobId"], "action": "snapshot"}),
                    aggregate_fn.Deps(self._s, self._repos()),
                )
        except Exception as e:
            logger.warning("snapshot after %s failed: %s", task["videoId"], e)

    def run(self, job_id: str) -> None:
        t0 = time.monotonic()
        repos = self._repos()
        try:
            collected = collect_fn.run(
                JobInput.model_validate({"jobId": job_id}),
                collect_fn.Deps(self._s, repos, self._c.youtube),
            )
            assert isinstance(collected, CollectOutput)
            refs = _json(collected)["videoRefs"]
            logger.info("job %s: %d videos", job_id, len(refs))
            with ThreadPoolExecutor(self._concurrency) as pool:
                list(pool.map(self._video_then_snapshot, refs))
            agg = aggregate_fn.Deps(self._s, repos)
            while True:
                replaced = aggregate_fn.run(
                    AggregateInput.model_validate({"jobId": job_id, "action": "replace"}), agg
                )
                assert isinstance(replaced, ReplaceOutput)
                if replaced.replacement is None:
                    break
                self._video_then_snapshot(_json(replaced.replacement))
            aggregate_fn.run(AggregateInput.model_validate({"jobId": job_id}), agg)
            logger.info("job %s: done in %.0fs", job_id, time.monotonic() - t0)
        except Exception:
            logger.exception("job %s failed", job_id)
            repos.jobs.mutate(
                job_id, lambda j: j.model_copy(update={"status": "FAILED"}), datetime.now(UTC)
            )


class ThreadStarter:
    """JobStarter. Step Functions 실행 대신 스레드를 띄운다."""

    def __init__(self, run: Callable[[str], None]) -> None:
        self._run = run

    def start(self, job_id: str) -> str:
        threading.Thread(target=self._run, args=(job_id,), daemon=True).start()
        return f"local:{job_id}"


def make_handler(deps: api_fn.Deps) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _dispatch(self, method: str) -> None:
            path = urlparse(self.path).path.rstrip("/")
            parts = path.split("/")
            if path == "/public/jobs":
                route, params = f"{method} /public/jobs", {}
            elif len(parts) == 4 and parts[1:3] == ["public", "jobs"]:
                route, params = f"{method} /public/jobs/{{jobId}}", {"jobId": parts[3]}
            else:
                route, params = "", {}
            length = int(self.headers.get("content-length") or 0)
            event = {
                "routeKey": route,
                "pathParameters": params,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": self.rfile.read(length).decode() if length else None,
                "isBase64Encoded": False,
            }
            resp = api_fn.run(event, deps)
            body = resp["body"].encode()
            self.send_response(resp["statusCode"])
            for k, v in resp.get("headers", {}).items():
                self.send_header(k, v)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def log_message(self, format: str, *args: Any) -> None:
            # 경로만 남긴다(토큰은 헤더라 찍히지 않는다)
            logger.debug("%s %s", self.command, urlparse(self.path).path)

    return Handler


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--env-file", type=Path, default=Path("../experiments/.env"))
    p.add_argument("--port", type=int, default=8787)
    p.add_argument(
        "--gemini-models",
        default="gemini-3.5-flash-lite,gemini-3.1-flash-lite",
        help="구간 관찰 모델(선호 순, 쉼표). 비우면 --gemini-model로 영상 통째로 1회",
    )
    p.add_argument("--segment-sec", type=int, default=190, help="구간 길이(초)")
    p.add_argument("--fps", type=float, default=0.5)
    p.add_argument("--rpm", type=int, default=14, help="모델별 분당 요청 상한")
    p.add_argument("--gemini-model", default="gemini-3-flash-preview", help="통째로 1회 모드")
    p.add_argument(
        "--thinking", default="low", help="통째로 1회 모드: minimal|low|medium|high|none"
    )
    p.add_argument("--clip-sec", type=int, default=300, help="통째로 1회 모드: 0이면 전체 영상")
    p.add_argument("--llm-model", default="bedrock-haiku")
    p.add_argument("--concurrency", type=int, default=5, help="동시에 처리할 영상 수")
    p.add_argument("--gemini-concurrency", type=int, default=2, help="Gemini 동시 호출 수")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    env = load_env_file(a.env_file)
    missing = [k for k in REQUIRED_KEYS if not env.get(k)]
    if missing:
        raise SystemExit(f"{a.env_file}에 없는 값: {', '.join(missing)}")

    # moto가 가로채므로 실제 AWS로 나가지 않는다
    os.environ.update(
        AWS_ACCESS_KEY_ID="local", AWS_SECRET_ACCESS_KEY="local", AWS_DEFAULT_REGION=REGION
    )
    models = tuple(m.strip() for m in a.gemini_models.split(",") if m.strip())
    mode = (
        f"seg{a.segment_sec}-fps{a.fps}-{'+'.join(models)}"
        if models
        else f"{a.gemini_model}-{a.thinking}-{a.clip_sec}"
    )
    settings = Settings(
        analysis_version=f"local-v2-{mode}",  # 프롬프트 v2·MM:SS (결정 0006)
        gemini_model=a.gemini_model,
        gemini_models=models,
        gemini_segment_sec=a.segment_sec,
        gemini_fps=a.fps,
        gemini_rpm=a.rpm,
        bedrock_interpreter_model_id=a.llm_model,
    )

    with mock_aws():
        create_tables(boto3.client("dynamodb", region_name=REGION), settings)
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=settings.bucket)
        repos = Repos.from_settings(settings)
        gemini: GeminiObserver
        if models:
            # 구간 관찰기가 모델별 분당 상한으로 줄을 세우고, 실패·얇은 구간은 직접 다시 보낸다
            gemini = SegmentedObserver(
                models,
                duration_of=video_duration(repos, lambda: datetime.now(UTC)),
                api_key=env["GEMINI_API_KEY"],
                limiter=RateLimiter(a.rpm),
                segment_sec=a.segment_sec,
                fps=a.fps,
                media_resolution=settings.gemini_media_resolution,
            )
        else:
            gemini = ThrottledObserver(
                GeminiYouTubeObserver(
                    a.gemini_model,
                    api_key=env["GEMINI_API_KEY"],
                    media_resolution=settings.gemini_media_resolution,
                    thinking_level=None if a.thinking == "none" else a.thinking,
                    clip_sec=a.clip_sec or None,
                ),
                a.gemini_concurrency,
            )
        clients = Clients(
            youtube=YouTubeDataApi(env["YOUTUBE_API_KEY"]),
            gemini=gemini,
            places=PlacesTextSearch(env["PLACES_API_KEY"]),
            llm=ChunkedInterpreter(  # 게이트웨이 출력 4,096토큰 한도 → 단서 80개씩
                GatewayChatInterpreter(
                    a.llm_model, api_key=env["LLM_API_KEY"], base_url=env["LLM_BASE_URL"]
                )
            ),
        )
        pipeline = LocalPipeline(settings, clients, a.concurrency)
        deps = api_fn.Deps(settings, repos, ThreadStarter(pipeline.run))
        server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(deps))
        logger.info(
            "listening on http://127.0.0.1:%d (gemini=%s llm=%s)",
            a.port,
            mode,
            a.llm_model,
        )
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()


if __name__ == "__main__":
    main()

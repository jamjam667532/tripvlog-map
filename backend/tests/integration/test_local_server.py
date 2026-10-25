"""local/server.py: 스레드 파이프라인과 HTTP 어댑터가 api_public 계약대로 동작하는지.

외부 API는 가짜.
"""

import json
import threading
import time
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from typing import Any

from functions.api_public import handler as api
from local.server import Clients, LocalPipeline, ThreadStarter, make_handler
from shared.repos import Repos
from shared.settings import Settings
from tests.integration.factories import (
    V1,
    V2,
    osaka_interpretation,
    osaka_observation,
    second_video,
)
from tests.integration.test_e2e_osaka import make_world


def test_local_server_runs_pipeline_in_background(repos: Repos, settings: Settings) -> None:
    w = make_world(
        [V1, V2], {V1: (osaka_observation(), osaka_interpretation()), V2: second_video()}
    )
    pipeline = LocalPipeline(
        settings, Clients(w.youtube, w.gemini, w.places, w.bedrock), concurrency=2
    )
    deps = api.Deps(settings, repos, ThreadStarter(pipeline.run))
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(deps))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        body = json.dumps({"requestId": str(uuid.uuid4()), "destination": "오사카"}).encode()
        req = urllib.request.Request(
            f"{base}/public/jobs", data=body, headers={"content-type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 202
            created: dict[str, Any] = json.loads(resp.read())

        job: dict[str, Any] = {}
        for _ in range(100):
            get = urllib.request.Request(
                f"{base}/public/jobs/{created['jobId']}",
                headers={"X-Guest-Access-Token": created["guestAccessToken"]},
            )
            with urllib.request.urlopen(get) as resp:
                job = json.loads(resp.read())
            if job["status"] in ("SUCCEEDED", "PARTIAL", "FAILED"):
                break
            time.sleep(0.05)

        assert job["status"] == "SUCCEEDED"
        assert [p["placeId"] for p in job["result"]["places"]] == ["ChIJ_ichiran"]
        assert w.gemini.calls == {V1: 1, V2: 1}
    finally:
        server.shutdown()

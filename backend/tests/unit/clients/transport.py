"""요청을 기록하고 정해 둔 응답을 돌려주는 가짜 HTTP 전송."""

import json
from collections.abc import Callable
from typing import Any

from shared.clients.http import HttpRequest, HttpResponse


class RecordingTransport:
    def __init__(self, respond: Callable[[HttpRequest], tuple[int, Any]]) -> None:
        self._respond = respond
        self.requests: list[HttpRequest] = []

    def __call__(self, req: HttpRequest, timeout: float) -> HttpResponse:
        self.requests.append(req)
        status, body = self._respond(req)
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return HttpResponse(status, raw)

    def body(self, i: int = -1) -> Any:
        raw = self.requests[i].body
        return json.loads(raw) if raw else None

"""작은 HTTP 전송 계층. 테스트에서는 transport를 바꿔 끼워 실제 호출을 막는다."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from shared.clients.errors import ExternalApiError


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


Transport = Callable[[HttpRequest, float], HttpResponse]


def urllib_transport(req: HttpRequest, timeout: float) -> HttpResponse:
    r = urllib.request.Request(req.url, data=req.body, headers=dict(req.headers), method=req.method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return HttpResponse(resp.status, resp.read())
    except urllib.error.HTTPError as e:
        return HttpResponse(e.code, e.read())


def request_json(
    transport: Transport, service: str, req: HttpRequest, timeout: float
) -> dict[str, Any]:
    try:
        resp = transport(req, timeout)
    except OSError as e:
        raise ExternalApiError(service, None, type(e).__name__) from None
    if not 200 <= resp.status < 300:
        # 응답 본문에는 요청 URL(키 포함)이 되돌아올 수 있으므로 상태 코드만 남긴다
        raise ExternalApiError(service, resp.status)
    data = json.loads(resp.body or b"{}")
    if not isinstance(data, dict):
        raise ExternalApiError(service, resp.status, "unexpected body")
    return data

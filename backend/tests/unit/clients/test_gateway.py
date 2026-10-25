import json
from typing import Any

import pytest

from shared.clients.bedrock import GatewayChatInterpreter
from shared.clients.errors import ExternalApiError, InvalidModelOutput
from shared.clients.http import HttpRequest, HttpResponse
from tests.unit.clients.test_bedrock import OBS, _good


def _chat(text: str) -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
        }
    ).encode()


class Seq:
    """정해 둔 응답을 차례로 돌려주는 전송 계층."""

    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.requests: list[HttpRequest] = []

    def __call__(self, req: HttpRequest, timeout: float) -> HttpResponse:
        self.requests.append(req)
        return self.responses.pop(0)


def _client(transport: Seq, sleeps: list[float] | None = None) -> GatewayChatInterpreter:
    return GatewayChatInterpreter(
        "bedrock-haiku",
        api_key="sk-test",
        base_url="https://gw.example/v1/",
        transport=transport,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_interprets_and_links_to_observation() -> None:
    t = Seq(HttpResponse(200, _chat(_good())))
    out = _client(t).interpret(OBS, "v1")
    assert out.result.video_id == "abc"
    assert out.result.analysis_version == "v1"
    assert [c.candidate_id for c in out.result.candidates] == [
        "c1"
    ]  # 없는 단서(7)를 가리킨 후보는 버린다
    assert (out.input_tokens, out.output_tokens) == (1000, 200)
    req = t.requests[0]
    assert req.url == "https://gw.example/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer sk-test"
    body: dict[str, Any] = json.loads(req.body or b"")
    assert body["model"] == "bedrock-haiku"


def test_retries_once_on_invalid_output() -> None:
    t = Seq(HttpResponse(200, _chat("not json")), HttpResponse(200, _chat(_good())))
    out = _client(t).interpret(OBS, "v1")
    assert len(t.requests) == 2
    assert out.input_tokens == 2000


def test_invalid_twice_fails() -> None:
    t = Seq(HttpResponse(200, _chat("x")), HttpResponse(200, _chat("y")))
    with pytest.raises(InvalidModelOutput):
        _client(t).interpret(OBS, "v1")


def test_budget_exceeded_is_not_retried() -> None:
    t = Seq(HttpResponse(400, b'{"error": {"message": "Budget has been exceeded"}}'))
    with pytest.raises(ExternalApiError, match="BUDGET_EXCEEDED"):
        _client(t).interpret(OBS, "v1")
    assert len(t.requests) == 1


def test_rate_limit_backs_off_then_succeeds() -> None:
    sleeps: list[float] = []
    t = Seq(HttpResponse(429, b"{}"), HttpResponse(429, b"{}"), HttpResponse(200, _chat(_good())))
    _client(t, sleeps).interpret(OBS, "v1")
    assert sleeps == [1.0, 2.0]


def test_auth_error_is_not_retried() -> None:
    t = Seq(HttpResponse(401, b"{}"))
    with pytest.raises(ExternalApiError):
        _client(t).interpret(OBS, "v1")
    assert len(t.requests) == 1

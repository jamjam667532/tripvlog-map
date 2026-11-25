"""[M8] 게이트웨이 임베딩 클라이언트 (결정 0011). 실제 게이트웨이는 부르지 않는다."""

import json
from typing import Any

import pytest

from shared.clients.embeddings import BATCH, GatewayEmbedder
from shared.clients.errors import ExternalApiError
from shared.clients.http import HttpRequest
from tests.unit.clients.transport import RecordingTransport


def _reply(req: HttpRequest) -> tuple[int, Any]:
    texts = json.loads(req.body or b"{}")["input"]
    rows = [{"index": i, "embedding": [float(i), 1.0]} for i in range(len(texts))]
    return 200, {"data": list(reversed(rows)), "usage": {"prompt_tokens": len(texts)}}


def test_embed_batches_and_keeps_input_order() -> None:
    t = RecordingTransport(_reply)
    e = GatewayEmbedder("bedrock-titan-embed-v2", api_key="k", base_url="https://gw/", transport=t)
    vectors = e.embed([f"t{i}" for i in range(BATCH + 2)])
    assert len(t.requests) == 2 and t.requests[0].url == "https://gw/embeddings"
    assert t.body(0)["model"] == "bedrock-titan-embed-v2"
    assert [v[0] for v in vectors[:3]] == [0.0, 1.0, 2.0]  # index 순으로 되돌린다
    assert e.tokens_used == BATCH + 2


def test_bad_body_is_external_error() -> None:
    t = RecordingTransport(lambda req: (200, {"data": []}))
    with pytest.raises(ExternalApiError):
        GatewayEmbedder("m", api_key="k", base_url="https://gw", transport=t).embed(["a"])


def test_budget_exceeded_is_not_retried() -> None:
    t = RecordingTransport(lambda req: (400, b"Budget has been exceeded"))
    with pytest.raises(ExternalApiError) as e:
        GatewayEmbedder("m", api_key="k", base_url="https://gw", transport=t).embed(["a"])
    assert "BUDGET_EXCEEDED" in str(e.value) and len(t.requests) == 1

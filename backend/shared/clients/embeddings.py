"""[M8] 학교 게이트웨이 임베딩 (결정 0011).

모델은 별칭으로만 부른다(EMBEDDING_MODEL_ID, 예: bedrock-titan-embed-v2).

관심사와 영상 제목·설명을 같은 공간의 벡터로 바꿔 코사인 유사도로 비교한다.
보내는 것은 공개 영상·채널의 제목·설명과 관심사 이름뿐이다(사용자 ID·토큰 없음).
"""

import time
from collections.abc import Callable, Sequence
from typing import Protocol

from shared.clients.bedrock import gateway_post
from shared.clients.errors import ExternalApiError
from shared.clients.http import Transport, urllib_transport

BATCH = 16
MAX_TEXT_CHARS = 800


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class GatewayEmbedder:
    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str,
        transport: Transport = urllib_transport,
        timeout_sec: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/embeddings"
        self._transport = transport
        self._timeout = timeout_sec
        self._sleep = sleep
        self.tokens_used = 0

    def __repr__(self) -> str:
        return f"GatewayEmbedder(model={self.model!r})"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            chunk = [t[:MAX_TEXT_CHARS] or " " for t in texts[i : i + BATCH]]
            data = gateway_post(
                self._transport,
                self._url,
                self._api_key,
                {"model": self.model, "input": chunk},
                self._timeout,
                self._sleep,
            )
            self.tokens_used += int((data.get("usage") or {}).get("prompt_tokens", 0) or 0)
            rows = sorted(data.get("data") or [], key=lambda r: r.get("index", 0))
            vectors = [r.get("embedding") for r in rows]
            if len(vectors) != len(chunk) or not all(isinstance(v, list) and v for v in vectors):
                raise ExternalApiError("llm-gateway", 200, "unexpected embedding body")
            out.extend([float(x) for x in v] for v in vectors)
        return out

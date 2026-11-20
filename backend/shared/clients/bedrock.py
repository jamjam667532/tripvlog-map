"""[2-3] Bedrock 해석 (spec §5.3). Converse API로 통일하고 모델 ID만 바꿔 쓴다.

- 구조화 출력(outputConfig.textFormat = json_schema)으로 InterpretationResult 형식을 강제한다.
  모델이 지원하지 않으면 structured_output=False로 두고 프롬프트의 JSON 지시에만 의존한다.
  TODO(verify): 모델별 구조화 출력 지원 여부 (Haiku 4.5, GPT 5.6 Luna)
- 검증 실패 시 이 영상의 Bedrock만 1회 재요청(결정 0002-5). Gemini는 다시 부르지 않는다.
- Places 응답은 이 클라이언트에 넘기지 않는다(관찰 결과만 입력).
"""

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from shared.clients.ai_schema import ai_json_schema
from shared.clients.errors import ExternalApiError, InvalidModelOutput
from shared.clients.http import HttpRequest, Transport, urllib_transport
from shared.clients.prompts import load_prompt
from shared.schemas.interpretation import InterpretationResult, link_to_observation
from shared.schemas.observation import ObservationResult

MAX_ATTEMPTS = 2  # 최초 1회 + 재요청 1회
GATEWAY_MAX_TOKENS = 8192  # 2026-11-20 확인: 게이트웨이가 8,192까지 받는다
MIN_SPLIT_CLUES = 20  # 묶음이 실패하면 반으로 나눠 다시 보낸다. 이보다 작으면 나누지 않는다

logger = logging.getLogger(__name__)
SCHEMA_NAME = "interpretation_result"


@dataclass(frozen=True)
class Interpretation:
    result: InterpretationResult
    input_tokens: int
    output_tokens: int


class BedrockInterpreter(Protocol):
    def interpret(
        self, observation: ObservationResult, analysis_version: str
    ) -> Interpretation: ...


def observation_prompt(observation: ObservationResult, analysis_version: str) -> str:
    clues = [{"index": i, **c.model_dump()} for i, c in enumerate(observation.clues)]
    payload = {
        "video_id": observation.video_id,
        "analysis_version": analysis_version,
        "clues": clues,
    }
    return json.dumps(payload, ensure_ascii=False)


def _error_fields(error: Exception) -> list[str]:
    """검증 오류의 필드 위치와 종류만. 모델이 쓴 값(input)은 남기지 않는다."""
    if not isinstance(error, ValidationError):
        return []
    fields = {
        ".".join(str(p) for p in e["loc"] if not isinstance(p, int)) + ":" + e["type"]
        for e in error.errors()
    }
    return sorted(fields)[:5]


def _strip_code_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()


class BedrockConverseInterpreter:
    def __init__(
        self,
        model_id: str,
        *,
        client: Any = None,
        region: str | None = None,
        structured_output: bool = True,
        max_tokens: int = 16384,  # 구간 관찰로 단서가 200~300개라 4096이면 출력이 잘린다
    ) -> None:
        self._client = client or boto3.client("bedrock-runtime", region_name=region)
        self._model_id = model_id
        self._structured = structured_output
        self._max_tokens = max_tokens
        self._schema = json.dumps(ai_json_schema(InterpretationResult), ensure_ascii=False)

    def __repr__(self) -> str:
        return f"BedrockConverseInterpreter(model_id={self._model_id!r})"

    def _request(self, user_text: str) -> dict[str, Any]:
        req: dict[str, Any] = {
            "modelId": self._model_id,
            "system": [{"text": load_prompt("interpret")}],
            "messages": [{"role": "user", "content": [{"text": user_text}]}],
            "inferenceConfig": {"maxTokens": self._max_tokens, "temperature": 0.0},
        }
        if self._structured:
            req["outputConfig"] = {
                "textFormat": {
                    "type": "json_schema",
                    "structure": {"jsonSchema": {"schema": self._schema, "name": SCHEMA_NAME}},
                }
            }
        return req

    def interpret(self, observation: ObservationResult, analysis_version: str) -> Interpretation:
        req = self._request(observation_prompt(observation, analysis_version))
        input_tokens = output_tokens = 0
        for _ in range(MAX_ATTEMPTS):
            try:
                resp = self._client.converse(**req)
            except ClientError as e:
                status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                raise ExternalApiError("bedrock", status, e.response["Error"]["Code"]) from None
            except BotoCoreError as e:
                raise ExternalApiError("bedrock", None, type(e).__name__) from None
            usage = resp.get("usage", {})
            input_tokens += int(usage.get("inputTokens", 0))
            output_tokens += int(usage.get("outputTokens", 0))
            text = "".join(
                block.get("text", "")
                for block in resp.get("output", {}).get("message", {}).get("content", [])
            )
            try:
                data = json.loads(_strip_code_fence(text))
                # video_id·analysis_version은 모델 출력이 아니라 입력 값으로 고정한다
                data.update(video_id=observation.video_id, analysis_version=analysis_version)
                parsed = InterpretationResult.model_validate(data)
            except (json.JSONDecodeError, ValidationError, AttributeError, TypeError):
                continue
            return Interpretation(
                link_to_observation(parsed, observation), input_tokens, output_tokens
            )
        raise InvalidModelOutput("bedrock", MAX_ATTEMPTS)


class GatewayChat:
    """학교 LLM 게이트웨이(OpenAI 호환 chat.completions) 한 번 호출 (결정 0007-1).

    해석(GatewayChatInterpreter)과 취향 라벨(clients/taste.py)이 같이 쓴다.
    - 'Budget has been exceeded' → 재시도 없이 BUDGET_EXCEEDED
    - 429 → 지수 백오프 최대 3회
    - 그 밖의 4xx·5xx → 재시도 없이 실패
    - disable_thinking: 게이트웨이의 bedrock-haiku는 생각(thinking)을 켠 채 응답한다
      (2026-11-20 확인, 응답에 thinking_blocks). 보이지 않는 생각 토큰이 max_tokens를
      먼저 써서 JSON이 잘리므로 끈다.
      끄면 같은 입력에서 출력이 끝까지 나오고 응답도 약 2배 빠르다.
    """

    RATE_LIMIT_RETRIES = 3

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str,
        transport: Transport = urllib_transport,
        timeout_sec: float = 120.0,
        max_tokens: int = GATEWAY_MAX_TOKENS,
        sleep: Callable[[float], None] = time.sleep,
        disable_thinking: bool = True,
    ) -> None:
        self.model = model
        self._disable_thinking = disable_thinking
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._transport = transport
        self._timeout = timeout_sec
        self._max_tokens = max_tokens
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"GatewayChat(model={self.model!r})"

    def complete(self, system: str, user_text: str) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.0,
            "max_tokens": self._max_tokens,
            **({"thinking": {"type": "disabled"}} if self._disable_thinking else {}),
        }
        req = HttpRequest(
            "POST",
            self._url,
            {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            json.dumps(body, ensure_ascii=False).encode(),
        )
        for attempt in range(self.RATE_LIMIT_RETRIES + 1):
            try:
                resp = self._transport(req, self._timeout)
            except OSError as e:
                raise ExternalApiError("llm-gateway", None, type(e).__name__) from None
            if b"Budget has been exceeded" in resp.body:
                raise ExternalApiError("llm-gateway", resp.status, "BUDGET_EXCEEDED")
            if resp.status == 429 and attempt < self.RATE_LIMIT_RETRIES:
                self._sleep(2.0**attempt)
                continue
            if not 200 <= resp.status < 300:
                raise ExternalApiError("llm-gateway", resp.status)
            data = json.loads(resp.body or b"{}")
            if not isinstance(data, dict):
                raise ExternalApiError("llm-gateway", resp.status, "unexpected body")
            return data
        raise ExternalApiError("llm-gateway", 429)


def message_text(data: dict[str, Any]) -> str:
    """chat.completions 응답의 본문. 코드 울타리(```)는 벗긴다."""
    return _strip_code_fence(data["choices"][0]["message"]["content"] or "")


class GatewayChatInterpreter:
    """학교 LLM 게이트웨이로 Bedrock 모델을 불러 해석한다 (결정 0007-1).

    모델은 별칭으로만 부른다(예: bedrock-haiku). 키·주소는 호출하는 쪽이 설정에서 읽어 넘긴다.
    오류 처리는 GatewayChat. 형식 검증 실패는 1회 재요청(429 재시도와 따로 센다).
    TODO(verify): response_format json_schema가 게이트웨이를 거쳐 적용되는지. 확인 전에는 끈다.
    """

    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        base_url: str,
        transport: Transport = urllib_transport,
        timeout_sec: float = 120.0,
        max_tokens: int = GATEWAY_MAX_TOKENS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._model = model
        self._chat = GatewayChat(
            model,
            api_key=api_key,
            base_url=base_url,
            transport=transport,
            timeout_sec=timeout_sec,
            max_tokens=max_tokens,
            sleep=sleep,
        )
        # 게이트웨이는 구조화 출력 강제를 아직 확인하지 못했으므로 스키마를 프롬프트로 준다
        schema = json.dumps(ai_json_schema(InterpretationResult), ensure_ascii=False)
        self._system = (
            load_prompt("interpret")
            + "\n\n## 출력 JSON 스키마 (반드시 이 형식 그대로, JSON 하나만 출력)\n"
            + schema
        )

    def __repr__(self) -> str:
        return f"GatewayChatInterpreter(model={self._model!r})"

    def _call(self, user_text: str) -> dict[str, Any]:
        return self._chat.complete(self._system, user_text)

    def interpret(self, observation: ObservationResult, analysis_version: str) -> Interpretation:
        user_text = observation_prompt(observation, analysis_version)
        input_tokens = output_tokens = 0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            data = self._call(user_text)
            usage = data.get("usage") or {}
            input_tokens += int(usage.get("prompt_tokens", 0))
            output_tokens += int(usage.get("completion_tokens", 0))
            choices = data.get("choices")
            finish = (
                choices[0].get("finish_reason") if isinstance(choices, list) and choices else None
            )
            try:
                text = data["choices"][0]["message"]["content"] or ""
                parsed_json = json.loads(_strip_code_fence(text))
                parsed_json.update(video_id=observation.video_id, analysis_version=analysis_version)
                parsed = InterpretationResult.model_validate(parsed_json)
            except (
                KeyError,
                IndexError,
                json.JSONDecodeError,
                ValidationError,
                AttributeError,
                TypeError,
            ) as e:
                # 원인만 남긴다(모델이 쓴 내용은 남기지 않는다)
                raw_error = data.get("error")
                gateway_error: dict[str, Any] = raw_error if isinstance(raw_error, dict) else {}
                logger.warning(
                    "interpret output rejected: attempt=%d error=%s finish=%s clues=%d "
                    "out_tokens=%s fields=%s body_keys=%s gateway_error=%s",
                    attempt,
                    type(e).__name__,
                    finish,
                    len(observation.clues),
                    usage.get("completion_tokens"),
                    _error_fields(e),
                    sorted(data)[:8],
                    gateway_error.get("type") or gateway_error.get("code"),
                )
                if finish == "length":
                    break  # 출력 한도에 잘렸다. 같은 입력을 다시 보내도 또 잘린다 → 나눠서 보낸다
                continue
            return Interpretation(
                link_to_observation(parsed, observation), input_tokens, output_tokens
            )
        raise InvalidModelOutput("llm-gateway", MAX_ATTEMPTS)


class ChunkedInterpreter:
    """단서가 많으면 나눠 해석하고 합친다.

    구간 관찰로 단서가 200~300개가 되면 해석 JSON이 출력 한도에 잘린다(finish_reason=length).
    생각을 끈 상태에서 단서 20개의 출력이 약 2천 토큰이었다(2026-11-20). 그래서 단서를
    max_clues개(기본 40, 약 4천 토큰)씩 나눠 각각 해석하고,
    clue_refs는 전체 관찰 기준 번호로 되돌린다.
    실패한 묶음은 반으로 나눠 한 번 더 보낸다(min_split개 이하면 나누지 않는다). 출력이 길어
    한도에 잘리는 경우를 막는다. 일부 묶음이 실패해도 나머지로 결과를 만들고, 모두 실패하면 예외.
    묶음 경계에 걸친 장소는 후보가 둘로 나뉠 수 있지만 [2-4] 매칭에서 같은 placeId로 모인다.
    """

    def __init__(
        self,
        inner: BedrockInterpreter,
        *,
        max_clues: int = 40,
        max_workers: int = 4,
        min_split: int = MIN_SPLIT_CLUES,
    ):
        self._inner = inner
        self._max_clues = max_clues
        self._max_workers = max_workers
        self._min_split = min_split

    def __repr__(self) -> str:
        return f"ChunkedInterpreter({self._inner!r}, max_clues={self._max_clues})"

    def _span(
        self, observation: ObservationResult, start: int, end: int, analysis_version: str
    ) -> list[tuple[int, Interpretation]]:
        """clues[start:end]를 해석한다. 실패하면 반으로 나눠 다시. (시작 번호, 결과) 목록."""
        part = observation.model_copy(update={"clues": observation.clues[start:end]})
        try:
            return [(start, self._inner.interpret(part, analysis_version))]
        except InvalidModelOutput:
            if end - start <= self._min_split:
                return []
            mid = (start + end) // 2
            return self._span(observation, start, mid, analysis_version) + self._span(
                observation, mid, end, analysis_version
            )

    def interpret(self, observation: ObservationResult, analysis_version: str) -> Interpretation:
        n_clues = len(observation.clues)
        starts = list(range(0, n_clues, self._max_clues)) or [0]
        with ThreadPoolExecutor(self._max_workers) as pool:
            spans = list(
                pool.map(
                    lambda s: self._span(
                        observation, s, min(s + self._max_clues, n_clues), analysis_version
                    ),
                    starts,
                )
            )
        pieces = [p for span in spans for p in span]
        if not pieces:
            raise InvalidModelOutput("llm-gateway", MAX_ATTEMPTS)
        if len(pieces) == 1 and pieces[0][0] == 0 and n_clues <= self._max_clues:
            return pieces[0][1]  # 한 번에 끝났으면 그대로
        results = [r for _, r in pieces]
        candidates = []
        for n, (offset, r) in enumerate(pieces):
            for c in r.result.candidates:
                candidates.append(
                    c.model_copy(
                        update={
                            "candidate_id": f"p{n + 1}-{c.candidate_id}",
                            "clue_refs": [offset + i for i in c.clue_refs],
                        }
                    )
                )
        merged = InterpretationResult(
            video_id=observation.video_id, analysis_version=analysis_version, candidates=candidates
        )
        return Interpretation(
            link_to_observation(merged, observation),
            sum(r.input_tokens for r in results),
            sum(r.output_tokens for r in results),
        )

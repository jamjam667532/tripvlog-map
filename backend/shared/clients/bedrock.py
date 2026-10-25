"""[2-3] Bedrock 해석 (spec §5.3). Converse API로 통일하고 모델 ID만 바꿔 쓴다.

- 구조화 출력(outputConfig.textFormat = json_schema)으로 InterpretationResult 형식을 강제한다.
  모델이 지원하지 않으면 structured_output=False로 두고 프롬프트의 JSON 지시에만 의존한다.
  TODO(verify): 모델별 구조화 출력 지원 여부 (Haiku 4.5, GPT 5.6 Luna)
- 검증 실패 시 이 영상의 Bedrock만 1회 재요청(결정 0002-5). Gemini는 다시 부르지 않는다.
- Places 응답은 이 클라이언트에 넘기지 않는다(관찰 결과만 입력).
"""

import json
import time
from collections.abc import Callable
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
        max_tokens: int = 4096,
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


class GatewayChatInterpreter:
    """학교 LLM 게이트웨이(OpenAI 호환 chat.completions)로 Bedrock 모델을 부른다 (결정 0007-1).

    모델은 별칭으로만 부른다(예: bedrock-haiku). 키·주소는 호출하는 쪽이 설정에서 읽어 넘긴다.
    - 'Budget has been exceeded' → 재시도 없이 BUDGET_EXCEEDED
    - 429 → 지수 백오프 최대 3회 (형식 검증 재요청과 따로 센다)
    - 그 밖의 4xx·5xx → 재시도 없이 실패
    TODO(verify): response_format json_schema가 게이트웨이를 거쳐 적용되는지. 확인 전에는 끈다.
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
        max_tokens: int = 4096,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._transport = transport
        self._timeout = timeout_sec
        self._max_tokens = max_tokens
        self._sleep = sleep
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
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.0,
            "max_tokens": self._max_tokens,
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

    def interpret(self, observation: ObservationResult, analysis_version: str) -> Interpretation:
        user_text = observation_prompt(observation, analysis_version)
        input_tokens = output_tokens = 0
        for _ in range(MAX_ATTEMPTS):
            data = self._call(user_text)
            usage = data.get("usage") or {}
            input_tokens += int(usage.get("prompt_tokens", 0))
            output_tokens += int(usage.get("completion_tokens", 0))
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
            ):
                continue
            return Interpretation(
                link_to_observation(parsed, observation), input_tokens, output_tokens
            )
        raise InvalidModelOutput("llm-gateway", MAX_ATTEMPTS)

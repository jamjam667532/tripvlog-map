"""[2-3] Bedrock 해석 (spec §5.3). Converse API로 통일하고 모델 ID만 바꿔 쓴다.

- 구조화 출력(outputConfig.textFormat = json_schema)으로 InterpretationResult 형식을 강제한다.
  모델이 지원하지 않으면 structured_output=False로 두고 프롬프트의 JSON 지시에만 의존한다.
  TODO(verify): 모델별 구조화 출력 지원 여부 (Haiku 4.5, GPT 5.6 Luna)
- 검증 실패 시 이 영상의 Bedrock만 1회 재요청(결정 0002-5). Gemini는 다시 부르지 않는다.
- Places 응답은 이 클라이언트에 넘기지 않는다(관찰 결과만 입력).
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from shared.clients.ai_schema import ai_json_schema
from shared.clients.errors import ExternalApiError, InvalidModelOutput
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

"""[2-2] Gemini 관찰 (spec §5.2). 영상은 내려받지 않고 공개 YouTube URL만 넘긴다.

- JSON 모드 + ObservationResult 스키마. 검증 실패 시 1회 재요청, 그래도 실패면 InvalidModelOutput.
- 타임아웃: SDK < Lambda < Step Functions Task.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from shared.clients.ai_schema import ai_json_schema
from shared.clients.errors import ExternalApiError, InvalidModelOutput
from shared.clients.prompts import load_prompt
from shared.schemas.observation import ObservationResult

MAX_ATTEMPTS = 2  # 최초 1회 + 재요청 1회


def youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class Observation:
    result: ObservationResult
    tokens: int


class GeminiObserver(Protocol):
    def observe(self, video_id: str) -> Observation: ...


class GeminiYouTubeObserver:
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        client: Any = None,
        timeout_sec: float = 600.0,
        media_resolution: str = "MEDIA_RESOLUTION_LOW",
    ) -> None:
        if client is None and api_key is None:
            raise ValueError("api_key or client is required")
        self._client = client or genai.Client(api_key=api_key)
        self._model = model
        self._config = types.GenerateContentConfig(
            system_instruction=load_prompt("observe"),
            temperature=0.0,
            response_mime_type="application/json",
            response_json_schema=ai_json_schema(ObservationResult),
            media_resolution=types.MediaResolution(media_resolution),
            http_options=types.HttpOptions(timeout=int(timeout_sec * 1000)),
        )

    def __repr__(self) -> str:
        return f"GeminiYouTubeObserver(model={self._model!r})"

    def observe(self, video_id: str) -> Observation:
        contents = types.Content(
            role="user",
            parts=[
                types.Part(file_data=types.FileData(file_uri=youtube_url(video_id))),
                types.Part(text=f"video_id: {video_id}"),
            ],
        )
        tokens = 0
        for _ in range(MAX_ATTEMPTS):
            try:
                resp = self._client.models.generate_content(
                    model=self._model, contents=contents, config=self._config
                )
            except genai_errors.APIError as e:
                raise ExternalApiError("gemini", getattr(e, "code", None)) from None
            usage = getattr(resp, "usage_metadata", None)
            tokens += int(getattr(usage, "total_token_count", 0) or 0)
            try:
                parsed = ObservationResult.model_validate_json(resp.text or "")
            except ValidationError:
                continue
            # video_id는 모델 출력이 아니라 요청한 값으로 고정한다
            return Observation(parsed.model_copy(update={"video_id": video_id}), tokens)
        raise InvalidModelOutput("gemini", MAX_ATTEMPTS)

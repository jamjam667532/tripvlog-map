import json
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors

from shared.clients.errors import ExternalApiError, InvalidModelOutput
from shared.clients.gemini import GeminiYouTubeObserver

VALID = {
    "video_id": "WRONG_ID_FROM_MODEL",
    "clues": [
        {
            "start": "12:30",
            "end": "15:05",
            "clue_type": "SPEECH",
            "heard_name": "이치란",
            "seen_text": None,
            "utterance": "국물 맛있어요",
            "scene": None,
            "scene_daypart": "DAY",
            "uncertainty": [],
        }
    ],
}


class FakeModels:
    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(text=r, usage_metadata=SimpleNamespace(total_token_count=500))


def _observer(models: FakeModels) -> GeminiYouTubeObserver:
    return GeminiYouTubeObserver("gemini-test", client=SimpleNamespace(models=models))


def test_passes_public_youtube_url_and_json_schema() -> None:
    models = FakeModels(json.dumps(VALID))
    obs = _observer(models).observe("dQw4w9WgXcQ")
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    part = call["contents"].parts[0]
    assert part.file_data.file_uri == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    cfg = call["config"]
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema["type"] == "object"
    assert "관찰자" in cfg.system_instruction
    assert obs.result.video_id == "dQw4w9WgXcQ"  # 모델이 쓴 값이 아니라 요청 값
    assert (obs.result.clues[0].start_sec, obs.result.clues[0].end_sec) == (750, 905)  # MM:SS → 초
    assert obs.tokens == 500


def test_invalid_output_retried_once_then_succeeds() -> None:
    models = FakeModels("not json", json.dumps(VALID))
    obs = _observer(models).observe("abc")
    assert len(models.calls) == 2
    assert obs.tokens == 1000  # 두 번의 사용량을 모두 기록


def test_invalid_twice_raises() -> None:
    bad = json.dumps({**VALID, "clues": [{"clue_type": "GUESS"}]})
    models = FakeModels(bad, bad, json.dumps(VALID))
    with pytest.raises(InvalidModelOutput):
        _observer(models).observe("abc")
    assert len(models.calls) == 2


def test_api_error_is_external_error() -> None:
    err = genai_errors.ClientError(
        429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )
    with pytest.raises(ExternalApiError) as e:
        _observer(FakeModels(err)).observe("abc")
    assert e.value.status == 429


def test_requires_key_or_client() -> None:
    with pytest.raises(ValueError):
        GeminiYouTubeObserver("gemini-test")

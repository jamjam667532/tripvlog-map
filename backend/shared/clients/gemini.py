"""[2-2] Gemini 관찰 (spec §5.2). 영상은 내려받지 않고 공개 YouTube URL만 넘긴다.

- JSON 모드 + ObservationWire 스키마(재생 위치 "MM:SS", 결정 0006-1). 코드에서 초로 바꿔
  ObservationResult로 검증한다. 검증 실패 시 1회 재요청, 그래도 실패면 InvalidModelOutput.
- GeminiYouTubeObserver: 영상 하나를 한 번에 본다.
- SegmentedObserver: 영상을 약 3분 구간으로 잘라 동시에 보고 합친다(결정 0008, 실험 기록
  "구간 나눠 동시에"). 모델마다 분당 요청 수를 세어 넘치는 구간은 다음 1분으로 미룬다. 실패했거나
  얇게 돌아온 구간은 첫 번째(가장 좋은) 모델로 한 번 더 보내 결과를 합친다.
- 타임아웃: SDK < Lambda < Step Functions Task.
"""

import statistics
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from shared.clients.ai_schema import ai_json_schema
from shared.clients.errors import ExternalApiError, InvalidModelOutput
from shared.clients.prompts import load_prompt
from shared.schemas.observation import Clue, ObservationResult, ObservationWire

MAX_ATTEMPTS = 2  # 최초 1회 + 재요청 1회


def youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class Observation:
    result: ObservationResult
    tokens: int


class GeminiObserver(Protocol):
    def observe(self, video_id: str) -> Observation: ...


def _config(
    media_resolution: str, timeout_sec: float, thinking_level: str | None
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=load_prompt("observe"),
        temperature=0.0,
        response_mime_type="application/json",
        response_json_schema=ai_json_schema(ObservationWire),
        media_resolution=types.MediaResolution(media_resolution),
        http_options=types.HttpOptions(timeout=int(timeout_sec * 1000)),
        thinking_config=(
            types.ThinkingConfig(thinking_level=types.ThinkingLevel(thinking_level.upper()))
            if thinking_level
            else None
        ),
    )


def _video_content(
    video_id: str, *, start: int | None = None, end: int | None = None, fps: float | None = None
) -> types.Content:
    meta = None
    if start is not None or fps:
        meta = types.VideoMetadata(
            start_offset=f"{start}s" if start is not None else None,
            end_offset=f"{end}s" if end is not None else None,
            fps=fps or None,
        )
    return types.Content(
        role="user",
        parts=[
            types.Part(
                file_data=types.FileData(file_uri=youtube_url(video_id)), video_metadata=meta
            ),
            types.Part(text=f"video_id: {video_id}"),
        ],
    )


@dataclass(frozen=True)
class _Reply:
    result: ObservationResult
    tokens: int
    output_tokens: int


def _generate(
    client: Any,
    model: str,
    contents: types.Content,
    config: types.GenerateContentConfig,
    video_id: str,
    max_sec: int | None,
) -> _Reply:
    """한 번 부르고 검증한다. 형식이 틀리면 1회 다시 부른다."""
    tokens = 0
    for _ in range(MAX_ATTEMPTS):
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
        except genai_errors.APIError as e:
            raise ExternalApiError("gemini", getattr(e, "code", None)) from None
        usage = getattr(resp, "usage_metadata", None)
        tokens += int(getattr(usage, "total_token_count", 0) or 0)
        output = int(getattr(usage, "candidates_token_count", 0) or 0)
        try:
            wire = ObservationWire.model_validate_json(resp.text or "")
            # video_id는 모델 출력이 아니라 요청한 값으로 고정한다
            return _Reply(wire.to_result(video_id, max_sec=max_sec), tokens, output)
        except (ValidationError, ValueError):
            continue
    raise InvalidModelOutput("gemini", MAX_ATTEMPTS)


class GeminiYouTubeObserver:
    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        client: Any = None,
        timeout_sec: float = 600.0,
        media_resolution: str = "MEDIA_RESOLUTION_LOW",
        thinking_level: str | None = None,
        clip_sec: int | None = None,
    ) -> None:
        """thinking_level·clip_sec가 None이면 모델 기본·전체 영상."""
        if client is None and api_key is None:
            raise ValueError("api_key or client is required")
        self._client = client or genai.Client(api_key=api_key)
        self._model = model
        self._clip_sec = clip_sec
        self._config = _config(media_resolution, timeout_sec, thinking_level)

    def __repr__(self) -> str:
        return f"GeminiYouTubeObserver(model={self._model!r})"

    def observe(self, video_id: str) -> Observation:
        clip = self._clip_sec
        contents = _video_content(video_id, start=0 if clip else None, end=clip)
        reply = _generate(self._client, self._model, contents, self._config, video_id, None)
        return Observation(reply.result, reply.tokens)


class RateLimiter:
    """모델별 분당 요청 수. 꽉 차면 가장 오래된 요청이 1분을 지날 때까지 기다린다."""

    def __init__(
        self,
        per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._sent: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _trim(self, model: str, now: float) -> deque[float]:
        sent = self._sent.setdefault(model, deque())
        while sent and now - sent[0] >= 60.0:
            sent.popleft()
        return sent

    def free(self, model: str) -> int:
        with self._lock:
            return self._per_minute - len(self._trim(model, self._clock()))

    def acquire(self, model: str) -> None:
        while True:
            with self._lock:
                now = self._clock()
                sent = self._trim(model, now)
                if len(sent) < self._per_minute:
                    sent.append(now)
                    return
                wait = 60.0 - (now - sent[0])
            self._sleep(max(wait, 0.05))


def segment_bounds(duration_sec: int, segment_sec: int) -> list[tuple[int, int]]:
    """영상을 거의 같은 길이의 구간으로 나눈다. 구간 수 = 올림(길이 / segment_sec)."""
    count = max(1, -(-duration_sec // segment_sec))
    step = -(-duration_sec // count)
    return [(i * step, min((i + 1) * step, duration_sec)) for i in range(count)]


def _clue_key(c: Clue) -> tuple[int, str, str]:
    text = (c.seen_text or c.utterance or c.scene or c.heard_name or "")[:20]
    return (c.start_sec // 5, c.clue_type, text)


@dataclass
class _Segment:
    start: int
    end: int
    replies: list[_Reply]
    failed: bool = False


class SegmentedObserver:
    """영상을 구간으로 나눠 동시에 관찰하고 합친다.

    - models: 앞에서부터 선호 순. 구간마다 이번 1분에 여유가 가장 많은 모델을 고른다
      (같으면 앞 모델).
    - 얇은 구간: 실패, 1분당 단서 min_clues_per_min개 미만, 또는 출력 토큰이 다른 구간 중앙값의
      thin_ratio 미만. 첫 번째 모델로 한 번 더 보내 두 결과를 합친다(같은 5초·같은 글자는 한 번).
    - 모든 구간이 실패하면 예외. 일부만 실패하면 남은 구간으로 결과를 만든다.
    """

    def __init__(
        self,
        models: Sequence[str],
        *,
        duration_of: Callable[[str], int | None],
        api_key: str | None = None,
        client: Any = None,
        limiter: RateLimiter | None = None,
        segment_sec: int = 190,
        fps: float = 0.5,
        media_resolution: str = "MEDIA_RESOLUTION_LOW",
        thinking_level: str | None = None,
        timeout_sec: float = 300.0,
        max_workers: int = 16,
        min_clues_per_min: float = 2.0,
        thin_ratio: float = 0.25,
    ) -> None:
        if not models:
            raise ValueError("at least one model is required")
        if client is None and api_key is None:
            raise ValueError("api_key or client is required")
        self._client = client or genai.Client(api_key=api_key)
        self._models = list(models)
        self._duration_of = duration_of
        self._limiter = limiter or RateLimiter(14)
        self._segment_sec = segment_sec
        self._fps = fps
        self._config = _config(media_resolution, timeout_sec, thinking_level)
        self._pool = ThreadPoolExecutor(max_workers)
        self._min_per_min = min_clues_per_min
        self._thin_ratio = thin_ratio

    def __repr__(self) -> str:
        return f"SegmentedObserver(models={self._models!r}, segment_sec={self._segment_sec})"

    def _pick_model(self) -> str:
        return max(self._models, key=lambda m: (self._limiter.free(m), -self._models.index(m)))

    def _call(self, video_id: str, seg: _Segment, model: str, duration: int) -> None:
        self._limiter.acquire(model)
        contents = _video_content(video_id, start=seg.start, end=seg.end, fps=self._fps)
        try:
            seg.replies.append(
                _generate(self._client, model, contents, self._config, video_id, duration)
            )
        except (ExternalApiError, InvalidModelOutput):
            seg.failed = True

    def _thin(self, seg: _Segment, median_out: float) -> bool:
        if not seg.replies:
            return True
        reply = seg.replies[-1]
        minutes = max(seg.end - seg.start, 1) / 60
        few = len(reply.result.clues) < self._min_per_min * minutes
        return few or reply.output_tokens < median_out * self._thin_ratio

    def observe(self, video_id: str) -> Observation:
        duration = self._duration_of(video_id)
        if not duration:
            raise ExternalApiError("gemini-duration", None)  # 길이를 모르면 구간을 못 나눈다
        segs = [_Segment(s, e, []) for s, e in segment_bounds(duration, self._segment_sec)]

        first = [
            self._pool.submit(self._call, video_id, seg, self._pick_model(), duration)
            for seg in segs
        ]
        for f in first:
            f.result()

        outs = [seg.replies[-1].output_tokens for seg in segs if seg.replies]
        median_out = statistics.median(outs) if outs else 0.0
        redo = [seg for seg in segs if self._thin(seg, median_out)]
        again = [
            self._pool.submit(self._call, video_id, seg, self._models[0], duration) for seg in redo
        ]
        for f in again:
            f.result()

        if not any(seg.replies for seg in segs):
            raise InvalidModelOutput("gemini", MAX_ATTEMPTS)
        seen: set[tuple[int, str, str]] = set()
        clues: list[Clue] = []
        for seg in segs:
            for reply in seg.replies:
                for c in reply.result.clues:
                    if (key := _clue_key(c)) not in seen:
                        seen.add(key)
                        clues.append(c)
        clues.sort(key=lambda c: c.start_sec)
        tokens = sum(r.tokens for seg in segs for r in seg.replies)
        return Observation(ObservationResult(video_id=video_id, clues=clues), tokens)

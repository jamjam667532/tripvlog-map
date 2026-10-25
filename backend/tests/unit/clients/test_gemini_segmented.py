"""[2-2] 구간 관찰기(SegmentedObserver)와 분당 요청 수 제한. 실제 Gemini는 부르지 않는다."""

import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors

from shared.clients.errors import InvalidModelOutput
from shared.clients.gemini import RateLimiter, SegmentedObserver, segment_bounds
from shared.schemas.observation import ObservationWire, timestamp_to_sec


def _mmss(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _wire(start: int, n: int, text: str = "자막") -> str:
    """구간 시작부터 10초 간격으로 단서 n개."""
    clues = [
        {
            "start": _mmss(start + 10 * i),
            "end": _mmss(start + 10 * i + 3),
            "clue_type": "SCREEN_TEXT",
            "seen_text": f"{text} {start + 10 * i}",
        }
        for i in range(n)
    ]
    return json.dumps({"video_id": "x", "clues": clues})


class FakeModels:
    """reply(모델, 구간 시작, 그 구간 몇 번째 호출) → (응답 글 또는 예외, 출력 토큰)."""

    def __init__(self, reply: Any) -> None:
        self._reply = reply
        self.calls: list[tuple[str, int]] = []
        self._lock = threading.Lock()

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        start = int(contents.parts[0].video_metadata.start_offset.removesuffix("s"))
        with self._lock:
            self.calls.append((model, start))
            n = sum(1 for _, s in self.calls if s == start)  # 이 구간을 몇 번째 부르는지
        text, output = self._reply(model, start, n)
        if isinstance(text, Exception):
            raise text
        usage = SimpleNamespace(total_token_count=1000 + output, candidates_token_count=output)
        return SimpleNamespace(text=text, usage_metadata=usage)


def _observer(models: FakeModels, duration: int = 570, **kw: Any) -> SegmentedObserver:
    return SegmentedObserver(
        ["best", "second"],
        duration_of=lambda _: duration,
        client=SimpleNamespace(models=models),
        limiter=RateLimiter(100),
        segment_sec=190,
        **kw,
    )


def test_timestamp_parsing() -> None:
    assert timestamp_to_sec("15:51") == 951
    assert timestamp_to_sec("1:02:03") == 3723
    assert timestamp_to_sec("1551") is None
    assert timestamp_to_sec("15:61") is None


def test_wire_beyond_video_length_is_invalid() -> None:
    wire = ObservationWire.model_validate_json(_wire(590, 2))
    with pytest.raises(ValueError):
        wire.to_result("x", max_sec=595)


def test_segment_bounds_cover_video_evenly() -> None:
    assert segment_bounds(1121, 190) == [
        (0, 187),
        (187, 374),
        (374, 561),
        (561, 748),
        (748, 935),
        (935, 1121),
    ]
    assert segment_bounds(100, 190) == [(0, 100)]


def test_segments_sent_with_offsets_and_merged_in_order() -> None:
    models = FakeModels(lambda m, s, n: (_wire(s, 8), 4000))
    obs = _observer(models).observe("vid")
    starts = sorted(s for _, s in models.calls)
    assert starts == [0, 190, 380]  # 570초 → 3구간
    assert [c.start_sec for c in obs.result.clues] == sorted(c.start_sec for c in obs.result.clues)
    assert len(obs.result.clues) == 24
    assert obs.result.video_id == "vid"
    assert obs.tokens == 3 * 5000


def test_failed_segment_resent_to_best_model() -> None:
    err = genai_errors.ServerError(503, {"error": {"message": "busy", "status": "UNAVAILABLE"}})

    def reply(model: str, start: int, n: int) -> tuple[Any, int]:
        if start == 190 and n == 1:
            return err, 0
        return _wire(start, 8), 4000

    models = FakeModels(reply)
    obs = _observer(models).observe("vid")
    assert sum(1 for _, s in models.calls if s == 190) == 2
    assert models.calls[-1] == ("best", 190)
    assert any(190 <= c.start_sec < 380 for c in obs.result.clues)


def test_thin_segment_by_output_resent_and_merged() -> None:
    def reply(model: str, start: int, n: int) -> tuple[Any, int]:
        if start == 380 and n == 1:
            return _wire(start, 7, "짧은"), 400  # 다른 구간 출력 4000의 1/4 미만
        return _wire(start, 8, "보강" if start == 380 else "자막"), 4000

    models = FakeModels(reply)
    obs = _observer(models).observe("vid")
    seg3 = [c for c in obs.result.clues if c.start_sec >= 380]
    assert len(seg3) == 7 + 8  # 두 결과를 합친다(글자가 달라 중복 아님)


def test_duplicate_clues_across_retries_kept_once() -> None:
    def reply(model: str, start: int, n: int) -> tuple[Any, int]:
        return _wire(start, 1 if start == 0 else 8), 4000  # 첫 구간은 단서가 적어 다시 보냄

    obs = _observer(FakeModels(reply)).observe("vid")
    assert sum(1 for c in obs.result.clues if c.start_sec < 190) == 1


def test_all_segments_failed_raises() -> None:
    err = genai_errors.ClientError(
        429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    )
    with pytest.raises(InvalidModelOutput):
        _observer(FakeModels(lambda m, s, n: (err, 0))).observe("vid")


def test_rate_limiter_waits_for_the_minute_to_pass() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(sec: float) -> None:
        slept.append(sec)
        now[0] += sec

    limiter = RateLimiter(2, clock=lambda: now[0], sleep=sleep)
    limiter.acquire("m")
    now[0] = 10.0
    limiter.acquire("m")
    limiter.acquire("m")  # 세 번째는 첫 요청이 60초를 지날 때까지 기다린다
    assert slept and now[0] >= 60.0
    assert limiter.free("other") == 2  # 모델마다 따로 센다


def test_picks_model_with_more_free_slots() -> None:
    limiter = RateLimiter(3)
    for _ in range(3):
        limiter.acquire("best")
    models = FakeModels(lambda m, s, n: (_wire(s, 8), 4000))
    obs = SegmentedObserver(
        ["best", "second"],
        duration_of=lambda _: 180,
        client=SimpleNamespace(models=models),
        limiter=limiter,
    )
    obs.observe("vid")
    assert models.calls[0][0] == "second"

"""Step Functions "analyze" 흐름을 테스트에서 흉내 낸다 (결정 0004-1·2, schemas/events.py).

collect → 영상마다 [claim ─ANALYZE→ observe → interpret → match | REUSE | WAIT→재시도]
        (실패하면 claim action=fail) → aggregate(replace) 반복 → aggregate(aggregate)

M5의 ASL 정의도 같은 순서·같은 이벤트를 써야 한다. 단계 사이에는 핸들러 출력(JSON)만 넘긴다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from functions.aggregate import handler as aggregate_fn
from functions.claim import handler as claim_fn
from functions.collect import handler as collect_fn
from functions.interpret import handler as interpret_fn
from functions.match import handler as match_fn
from functions.observe import handler as observe_fn
from shared.schemas.events import (
    AggregateInput,
    AggregateOutput,
    ClaimOutput,
    CollectOutput,
    InterpretOutput,
    JobInput,
    ObserveOutput,
    ReplaceOutput,
    VideoTask,
)


class WaitRequested(Exception):
    """순차 실행에서는 다른 작업이 끝날 때까지 기다릴 수 없다."""


def _json(model: Any) -> dict[str, Any]:
    out: dict[str, Any] = model.model_dump(mode="json")
    return out


@dataclass
class Pipeline:
    collect: collect_fn.Deps
    claim: claim_fn.Deps
    observe: observe_fn.Deps
    interpret: interpret_fn.Deps
    match: match_fn.Deps
    aggregate: aggregate_fn.Deps
    on_wait: Callable[[VideoTask], None] = field(default=lambda task: _raise_wait(task))
    steps: list[str] = field(default_factory=list)

    def run_video(self, task: dict[str, Any]) -> None:
        """Map 항목 하나. 어느 단계에서든 예외가 나면 Catch → claim(action=fail)."""
        try:
            state = task
            while True:
                self.steps.append(f"claim:{task['videoId']}")
                claimed = claim_fn.run(state, self.claim)
                assert isinstance(claimed, ClaimOutput)
                if claimed.decision == "REUSE":
                    return
                if claimed.decision == "ANALYZE":
                    break
                self.on_wait(VideoTask.model_validate(task))  # Wait 30초 대신
                state = _json(claimed)
            self.steps.append(f"observe:{task['videoId']}")
            observed = observe_fn.run(VideoTask.model_validate(_json(claimed)), self.observe)
            self.steps.append(f"interpret:{task['videoId']}")
            interpreted = interpret_fn.run(
                ObserveOutput.model_validate(_json(observed)), self.interpret
            )
            self.steps.append(f"match:{task['videoId']}")
            match_fn.run(InterpretOutput.model_validate(_json(interpreted)), self.match)
        except Exception as e:
            self.steps.append(f"fail:{task['videoId']}")
            error = {"Error": type(e).__name__, "Cause": str(e)}
            claim_fn.run({**task, "action": "fail", "error": error}, self.claim)

    def run(self, job_id: str) -> AggregateOutput:
        collected = collect_fn.run(JobInput.model_validate({"jobId": job_id}), self.collect)
        assert isinstance(collected, CollectOutput)
        for item in _json(collected)["videoRefs"]:
            self.run_video(item)
        while True:
            replaced = aggregate_fn.run(
                AggregateInput.model_validate({"jobId": job_id, "action": "replace"}),
                self.aggregate,
            )
            assert isinstance(replaced, ReplaceOutput)
            if replaced.replacement is None:
                break
            self.run_video(_json(replaced.replacement))
        done = aggregate_fn.run(AggregateInput.model_validate({"jobId": job_id}), self.aggregate)
        assert isinstance(done, AggregateOutput)
        return done


def _raise_wait(task: VideoTask) -> None:
    raise WaitRequested(task.video_id)

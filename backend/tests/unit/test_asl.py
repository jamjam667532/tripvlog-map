"""[M5] Step Functions 정의(infra/asl/analyze.asl.json)가 코드와 어긋나지 않는지 본다.

실제 Step Functions는 부르지 않는다. 상태 연결, 함수 이름, 이벤트 키 이름만 검사한다.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from shared.schemas.events import AggregateInput, FailInput

ROOT = Path(__file__).resolve().parents[3]
ASL = json.loads((ROOT / "infra/asl/analyze.asl.json").read_text())
FUNCTIONS = ROOT / "backend/functions"


def _walk(states: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for name, state in states.items():
        out.append((name, state))
        if state["Type"] == "Map":
            out += _walk(state["ItemProcessor"]["States"])
    return out


def _targets(state: dict[str, Any]) -> list[str]:
    nxt = [state["Next"]] if "Next" in state else []
    nxt += [c["Next"] for c in state.get("Choices", [])]
    nxt += [c["Next"] for c in state.get("Catch", [])]
    if "Default" in state:
        nxt.append(state["Default"])
    return nxt


def _graphs() -> list[tuple[str, dict[str, Any]]]:
    graphs = [("root", ASL)]
    for name, state in _walk(ASL["States"]):
        if state["Type"] == "Map":
            graphs.append((name, state["ItemProcessor"]))
    return graphs


@pytest.mark.parametrize(("where", "graph"), _graphs())
def test_every_transition_points_to_a_state(where: str, graph: dict[str, Any]) -> None:
    states = graph["States"]
    assert graph["StartAt"] in states
    for name, state in states.items():
        for target in _targets(state):
            assert target in states, f"{where}.{name} → {target}"
        assert state["Type"] in {"Fail", "Succeed"} or "End" in state or _targets(state)


def test_lambda_names_match_function_folders_with_prefix() -> None:
    names = {
        state["Parameters"]["FunctionName"].rsplit(":", 1)[1]
        for _, state in _walk(ASL["States"])
        if state["Type"] == "Task"
    }
    assert names
    for fn in names:
        assert fn.startswith("sgu-clicktotrip-"), fn  # 결정 0007-4
        folder = fn.removeprefix("sgu-clicktotrip-").replace("-", "_")
        assert (FUNCTIONS / folder / "handler.py").is_file(), fn


def test_account_is_a_placeholder_and_region_is_seoul() -> None:
    text = json.dumps(ASL)
    assert "${account}" in text
    assert "ap-northeast-2" in text
    assert "us-east-1" not in text  # 결정 0007-1


def _payload(name: str) -> dict[str, Any]:
    states = dict(_walk(ASL["States"]))
    payload: dict[str, Any] = states[name]["Parameters"]["Payload"]
    return payload


def test_mark_failed_payload_is_a_valid_fail_event() -> None:
    values: dict[str, Any] = {
        "jobId": str(uuid.uuid4()),
        "videoId": "abc_123-XYZ",
        "channelId": "UC_channel-1",
        "analysisVersion": "v2-seg190",
        "error": {"Error": "SomeError", "Cause": "x"},
    }
    event = {
        k.removesuffix(".$"): values.get(k.removesuffix(".$"), v)
        for k, v in _payload("MarkFailed").items()
    }
    parsed = FailInput.model_validate(event)
    assert parsed.action == "fail"


@pytest.mark.parametrize("name", ["Snapshot", "Replace", "Aggregate"])
def test_aggregate_payloads_are_valid_events(name: str) -> None:
    event = {
        k.removesuffix(".$"): str(uuid.uuid4()) if k == "jobId.$" else v
        for k, v in _payload(name).items()
    }
    assert AggregateInput.model_validate(event).action == _payload(name)["action"]


def test_map_runs_one_video_at_a_time_until_global_rate_limit_exists() -> None:
    # docs/deploy-runbook.md §9-A: Gemini 분당 제한이 Lambda 전체에서 지켜지기 전에는 1
    assert ASL["States"]["AnalyzeVideos"]["MaxConcurrency"] == 1


def test_inline_map_and_replacement_loop() -> None:
    assert ASL["States"]["AnalyzeVideos"]["ItemProcessor"]["ProcessorConfig"]["Mode"] == "INLINE"
    assert ASL["States"]["WrapReplacement"]["Next"] == "AnalyzeVideos"

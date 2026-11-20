import json
from typing import Any

import boto3
import pytest
from botocore.stub import ANY, Stubber

from shared.clients.bedrock import BedrockConverseInterpreter
from shared.clients.errors import ExternalApiError, InvalidModelOutput
from shared.schemas.observation import ObservationResult

OBS = ObservationResult.model_validate(
    {
        "video_id": "abc",
        "clues": [
            {"start_sec": 750, "end_sec": 905, "clue_type": "SPEECH", "heard_name": "이치란"},
            {"start_sec": 760, "end_sec": 770, "clue_type": "SCREEN_TEXT", "seen_text": "一蘭"},
        ],
    }
)


def _candidate(cid: str, refs: list[int]) -> dict[str, Any]:
    return {
        "candidate_id": cid,
        "names": ["이치란", "一蘭"],
        "branch_hint": "도톤보리",
        "search_queries": ["一蘭 道頓堀"],
        "category": "RESTAURANT",
        "visit_status": "VISITED",
        "clue_refs": refs,
        "ratings": {
            "overall": "POSITIVE",
            "taste": "POSITIVE",
            "price": "NONE",
            "wait": "NONE",
            "service": "NONE",
        },
        "time_evidence": [],
    }


def _response(text: str) -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 1200, "outputTokens": 300, "totalTokens": 1500},
        "metrics": {"latencyMs": 900},
    }


def _good() -> str:
    return json.dumps(
        {
            "video_id": "x",
            "analysis_version": "x",
            "candidates": [_candidate("c1", [0, 1]), _candidate("c2", [7])],
        }
    )


@pytest.fixture
def client() -> Any:
    return boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


def _expected(structured: bool = True) -> dict[str, Any]:
    params: dict[str, Any] = {
        "modelId": "test-model",
        "system": ANY,
        "messages": ANY,
        "inferenceConfig": ANY,
    }
    if structured:
        params["outputConfig"] = ANY
    return params


def test_converse_request_is_valid_and_result_linked(client: Any) -> None:
    with Stubber(client) as stub:  # Stubber가 요청 형식을 실제 API 명세로 검사한다
        stub.add_response("converse", _response(_good()), _expected())
        out = BedrockConverseInterpreter("test-model", client=client).interpret(OBS, "v1-haiku45")
    assert [c.candidate_id for c in out.result.candidates] == ["c1"]  # 범위 밖 clue_refs 버림
    assert (out.result.video_id, out.result.analysis_version) == ("abc", "v1-haiku45")
    assert (out.input_tokens, out.output_tokens) == (1200, 300)


def test_request_contains_only_observation_and_schema(client: Any) -> None:
    interp = BedrockConverseInterpreter("test-model", client=client)
    req = interp._request("payload")
    fmt = req["outputConfig"]["textFormat"]
    assert fmt["type"] == "json_schema"
    schema = json.loads(fmt["structure"]["jsonSchema"]["schema"])
    assert "candidates" in schema["properties"]
    assert req["inferenceConfig"]["temperature"] == 0.0
    assert "관찰 기록을 해석" in req["system"][0]["text"]


def test_code_fenced_json_without_structured_output(client: Any) -> None:
    with Stubber(client) as stub:
        stub.add_response("converse", _response(f"```json\n{_good()}\n```"), _expected(False))
        out = BedrockConverseInterpreter(
            "test-model", client=client, structured_output=False
        ).interpret(OBS, "v1")
    assert len(out.result.candidates) == 1


def test_retry_once_on_invalid_then_succeed(client: Any) -> None:
    with Stubber(client) as stub:
        stub.add_response("converse", _response("죄송합니다"), _expected())
        stub.add_response("converse", _response(_good()), _expected())
        out = BedrockConverseInterpreter("test-model", client=client).interpret(OBS, "v1")
    assert out.input_tokens == 2400


def test_invalid_twice_raises(client: Any) -> None:
    bad = json.dumps({"candidates": [{**_candidate("c1", [0]), "category": "HOTEL"}]})
    with Stubber(client) as stub:
        stub.add_response("converse", _response(bad), _expected())
        stub.add_response("converse", _response(bad), _expected())
        with pytest.raises(InvalidModelOutput):
            BedrockConverseInterpreter("test-model", client=client).interpret(OBS, "v1")


def test_throttling_is_external_error(client: Any) -> None:
    with Stubber(client) as stub:
        stub.add_client_error("converse", "ThrottlingException", http_status_code=429)
        with pytest.raises(ExternalApiError) as e:
            BedrockConverseInterpreter("test-model", client=client).interpret(OBS, "v1")
    assert e.value.status == 429


def test_chunked_interpreter_splits_and_restores_clue_refs() -> None:
    from shared.clients.bedrock import ChunkedInterpreter, Interpretation
    from shared.schemas.interpretation import InterpretationResult
    from shared.schemas.observation import ObservationResult

    clues = [
        {"start_sec": i, "end_sec": i, "clue_type": "SCREEN_TEXT", "seen_text": f"가게{i}"}
        for i in range(5)
    ]
    obs = ObservationResult.model_validate({"video_id": "vid", "clues": clues})
    seen: list[int] = []

    class Inner:
        def interpret(self, o: ObservationResult, version: str) -> Interpretation:
            seen.append(len(o.clues))
            cand = {
                "candidate_id": "c1",
                "names": [o.clues[-1].seen_text],
                "category": "RESTAURANT",
                "visit_status": "VISITED",
                "clue_refs": [len(o.clues) - 1],  # 묶음 안 번호
            }
            res = InterpretationResult.model_validate(
                {"video_id": o.video_id, "analysis_version": version, "candidates": [cand]}
            )
            return Interpretation(res, 10, 5)

    out = ChunkedInterpreter(Inner(), max_clues=2).interpret(obs, "v")
    assert seen == [2, 2, 1]
    assert [c.clue_refs for c in out.result.candidates] == [[1], [3], [4]]  # 전체 번호로
    assert [c.names[0] for c in out.result.candidates] == ["가게1", "가게3", "가게4"]
    assert len({c.candidate_id for c in out.result.candidates}) == 3
    assert (out.input_tokens, out.output_tokens) == (30, 15)


def _inner_failing_above(limit: int, seen: list[int]) -> Any:
    """단서가 limit개를 넘으면 형식 오류를 내는 가짜 해석기(출력이 잘리는 상황)."""
    from shared.clients.bedrock import Interpretation
    from shared.schemas.interpretation import InterpretationResult
    from shared.schemas.observation import ObservationResult

    class Inner:
        def interpret(self, o: ObservationResult, version: str) -> Interpretation:
            seen.append(len(o.clues))
            if len(o.clues) > limit:
                raise InvalidModelOutput("llm-gateway", 2)
            cand = {
                "candidate_id": "c1",
                "names": [o.clues[0].seen_text],
                "category": "RESTAURANT",
                "visit_status": "VISITED",
                "clue_refs": [0],
            }
            res = InterpretationResult.model_validate(
                {"video_id": o.video_id, "analysis_version": version, "candidates": [cand]}
            )
            return Interpretation(res, 1, 1)

    return Inner()


def _obs(n: int) -> Any:
    from shared.schemas.observation import ObservationResult

    clues = [
        {"start_sec": i, "end_sec": i, "clue_type": "SCREEN_TEXT", "seen_text": f"가게{i}"}
        for i in range(n)
    ]
    return ObservationResult.model_validate({"video_id": "vid", "clues": clues})


def test_chunked_interpreter_splits_a_failed_chunk_in_half() -> None:
    from shared.clients.bedrock import ChunkedInterpreter

    seen: list[int] = []
    out = ChunkedInterpreter(_inner_failing_above(2, seen), max_clues=4, min_split=2).interpret(
        _obs(4), "v"
    )
    assert seen == [4, 2, 2]
    assert [c.clue_refs for c in out.result.candidates] == [[0], [2]]  # 전체 번호로


def test_chunked_interpreter_gives_up_at_min_split() -> None:
    from shared.clients.bedrock import ChunkedInterpreter

    seen: list[int] = []
    with pytest.raises(InvalidModelOutput):
        ChunkedInterpreter(_inner_failing_above(0, seen), max_clues=4, min_split=2).interpret(
            _obs(4), "v"
        )
    assert seen == [4, 2, 2]  # 2개 이하는 더 나누지 않는다


def test_gateway_truncated_output_is_not_resent_and_reason_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from shared.clients.bedrock import GatewayChatInterpreter
    from tests.unit.clients.transport import RecordingTransport

    cut = '{"candidates": [{"candidate_id": "c1", "names": ["비밀가게'
    reply = {
        "choices": [{"message": {"content": cut}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4096},
    }
    t = RecordingTransport(lambda req: (200, reply))
    gi = GatewayChatInterpreter("bedrock-haiku", api_key="k", base_url="https://gw", transport=t)
    with caplog.at_level("WARNING"), pytest.raises(InvalidModelOutput):
        gi.interpret(OBS, "v1")
    assert len(t.requests) == 1  # 잘린 출력은 같은 입력으로 다시 보내지 않는다
    assert "finish=length" in caplog.text and "out_tokens=4096" in caplog.text
    assert "비밀가게" not in caplog.text  # 모델이 쓴 내용은 남기지 않는다


def test_gateway_validation_failure_logs_field_names_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from shared.clients.bedrock import GatewayChatInterpreter
    from tests.unit.clients.transport import RecordingTransport

    bad = json.dumps({"candidates": [{**_candidate("c1", [0]), "category": "숨은값HOTEL"}]})
    reply = {"choices": [{"message": {"content": bad}, "finish_reason": "stop"}], "usage": {}}
    t = RecordingTransport(lambda req: (200, reply))
    gi = GatewayChatInterpreter("bedrock-haiku", api_key="k", base_url="https://gw", transport=t)
    with caplog.at_level("WARNING"), pytest.raises(InvalidModelOutput):
        gi.interpret(OBS, "v1")
    assert len(t.requests) == 2
    assert "candidates.category:literal_error" in caplog.text
    assert "숨은값" not in caplog.text

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

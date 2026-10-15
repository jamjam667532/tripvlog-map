"""fixture 기반 계약 테스트.

fixtures/contracts/<스키마>/valid_*.json 은 통과하고, invalid_*.json 은 거부돼야 한다.
새 fixture는 파일만 추가하면 자동으로 검사된다.
"""

import json
from pathlib import Path

import pytest
from _pytest.mark import ParameterSet
from pydantic import BaseModel, ValidationError

from shared.schemas.api import CreateJobRequest, GetJobResponse
from shared.schemas.events import FailInput, VideoTask
from shared.schemas.interpretation import InterpretationResult
from shared.schemas.items import JobItem, PlaceEvidenceItem, UserItem, VideoAnalysisItem
from shared.schemas.match import MatchSummary
from shared.schemas.observation import ObservationResult
from shared.schemas.result import JobResult

CONTRACTS = Path(__file__).parent.parent / "fixtures" / "contracts"

MODELS: dict[str, type[BaseModel]] = {
    "observation": ObservationResult,
    "interpretation": InterpretationResult,
    "create_job_request": CreateJobRequest,
    "get_job_response": GetJobResponse,
    "job_result": JobResult,
    "job_item": JobItem,
    "video_analysis_item": VideoAnalysisItem,
    "place_evidence_item": PlaceEvidenceItem,
    "user_item": UserItem,
    "match_summary": MatchSummary,
    "video_task": VideoTask,
    "fail_input": FailInput,
}


def _cases(prefix: str) -> list[ParameterSet]:
    return [
        pytest.param(MODELS[path.parent.name], path, id=f"{path.parent.name}/{path.stem}")
        for path in sorted(CONTRACTS.glob(f"*/{prefix}_*.json"))
    ]


def test_every_fixture_dir_has_a_model() -> None:
    dirs = {p.name for p in CONTRACTS.iterdir() if p.is_dir()}
    assert dirs == set(MODELS)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_every_model_has_valid_and_invalid_fixtures(name: str) -> None:
    assert list((CONTRACTS / name).glob("valid_*.json"))
    assert list((CONTRACTS / name).glob("invalid_*.json"))


@pytest.mark.parametrize(("model", "path"), _cases("valid"))
def test_valid_fixture_passes_and_round_trips(model: type[BaseModel], path: Path) -> None:
    parsed = model.model_validate_json(path.read_text(encoding="utf-8"))
    # 직렬화한 결과를 다시 읽어도 같아야 한다 (S3·DynamoDB 저장 후 재사용)
    assert model.model_validate_json(parsed.model_dump_json()) == parsed


@pytest.mark.parametrize(("model", "path"), _cases("invalid"))
def test_invalid_fixture_is_rejected(model: type[BaseModel], path: Path) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(json.loads(path.read_text(encoding="utf-8")))

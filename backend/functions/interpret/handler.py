"""[2-3] interpret: Bedrock으로 관찰 결과를 해석한다 (spec §5.3). Places 응답은 넘기지 않는다.

입력 observation S3 키 → 해석 결과를 S3 analysis/{videoId}/{version}/interpretation.json에 쓴다.
형식 검증 실패 시 이 영상의 Bedrock만 1회 재요청(클라이언트).
Gemini는 다시 부르지 않는다(결정 0002-5).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from shared.clients.bedrock import (
    BedrockConverseInterpreter,
    BedrockInterpreter,
    ChunkedInterpreter,
)
from shared.repos import Repos, analysis_key, with_metrics
from shared.schemas.events import InterpretOutput, ObserveOutput
from shared.schemas.observation import ObservationResult
from shared.settings import Settings, require


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    bedrock: BedrockInterpreter
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def run(event: ObserveOutput, deps: Deps) -> InterpretOutput:
    observation = deps.repos.blobs.get_model(event.observation_s3_key, ObservationResult)
    interpretation = deps.bedrock.interpret(observation, event.analysis_version)
    key = deps.repos.blobs.put_model(
        analysis_key(event.video_id, event.analysis_version, "interpretation"),
        interpretation.result,
    )
    now = deps.clock()
    deps.repos.video_analysis.record_step(
        event.video_id,
        event.analysis_version,
        job_id=str(event.job_id),
        now=int(now.timestamp()),
        lease_sec=deps.settings.lease_sec,
        interpretation_s3_key=key,
        bedrock_input_tokens=interpretation.input_tokens,
        bedrock_output_tokens=interpretation.output_tokens,
    )
    deps.repos.jobs.mutate(
        str(event.job_id),
        lambda j: with_metrics(
            j,
            bedrock_input_tokens=interpretation.input_tokens,
            bedrock_output_tokens=interpretation.output_tokens,
        ),
        now,
    )
    return InterpretOutput(
        **event.task_fields(),
        observation_s3_key=event.observation_s3_key,
        interpretation_s3_key=key,
    )


@lru_cache(maxsize=1)
def _deps() -> Deps:
    s = Settings.from_env()
    return Deps(
        settings=s,
        repos=Repos.from_settings(s),
        bedrock=ChunkedInterpreter(  # 구간 관찰로 단서가 많아 출력 한도를 넘지 않게 나눠 해석
            BedrockConverseInterpreter(
                require(s.bedrock_interpreter_model_id, "BEDROCK_INTERPRETER_MODEL_ID"),
                region=s.bedrock_region,
                structured_output=s.bedrock_structured_output,
            )
        ),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run(ObserveOutput.model_validate(event), _deps()).model_dump(mode="json")

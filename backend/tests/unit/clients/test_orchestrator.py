import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

from shared.clients.errors import ExternalApiError
from shared.clients.orchestrator import StepFunctionsStarter, execution_arn

ARN = "arn:aws:states:us-east-1:123456789012:stateMachine:analyze"
JOB = "3f1c2b7e-8a4d-4c1e-9b2a-1d2e3f4a5b6c"


class StubSfn:
    def __init__(self, error_code: str | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error_code

    def start_execution(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._error:
            response: Any = {
                "Error": {"Code": self._error},
                "ResponseMetadata": {"HTTPStatusCode": 400},
            }
            raise ClientError(response, "StartExecution")
        return {"executionArn": execution_arn(ARN, kwargs["name"])}


def test_start_uses_job_id_as_execution_name() -> None:
    sfn = StubSfn()
    arn = StepFunctionsStarter(ARN, client=sfn).start(JOB)
    assert arn == f"arn:aws:states:us-east-1:123456789012:execution:analyze:{JOB}"
    [call] = sfn.calls
    assert call["name"] == JOB and json.loads(call["input"]) == {"jobId": JOB}


def test_already_started_is_not_an_error() -> None:
    arn = StepFunctionsStarter(ARN, client=StubSfn("ExecutionAlreadyExists")).start(JOB)
    assert arn.endswith(f":execution:analyze:{JOB}")


def test_other_errors_raise_without_details() -> None:
    with pytest.raises(ExternalApiError) as e:
        StepFunctionsStarter(ARN, client=StubSfn("StateMachineDoesNotExist")).start(JOB)
    assert e.value.service == "stepfunctions" and e.value.status == 400

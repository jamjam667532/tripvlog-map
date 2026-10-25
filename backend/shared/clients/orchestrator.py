"""[0] Step Functions 실행 시작. 실행 이름은 jobId(같은 작업은 한 번만 시작된다)."""

import json
from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.clients.errors import ExternalApiError


class JobStarter(Protocol):
    def start(self, job_id: str) -> str:
        """실행을 시작하고 executionArn을 돌려준다."""
        ...


def execution_arn(state_machine_arn: str, name: str) -> str:
    return f"{state_machine_arn.replace(':stateMachine:', ':execution:', 1)}:{name}"


class StepFunctionsStarter:
    def __init__(self, state_machine_arn: str, *, client: Any = None) -> None:
        self._arn = state_machine_arn
        self._client = client or boto3.client("stepfunctions")

    def __repr__(self) -> str:
        return "StepFunctionsStarter()"

    def start(self, job_id: str) -> str:
        try:
            resp = self._client.start_execution(
                stateMachineArn=self._arn, name=job_id, input=json.dumps({"jobId": job_id})
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code == "ExecutionAlreadyExists":
                return execution_arn(self._arn, job_id)
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            raise ExternalApiError("stepfunctions", status, code) from None
        except BotoCoreError as e:
            raise ExternalApiError("stepfunctions", None, type(e).__name__) from None
        return str(resp["executionArn"])

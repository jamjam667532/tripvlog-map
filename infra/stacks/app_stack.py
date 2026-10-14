from typing import Any

import aws_cdk as cdk
from constructs import Construct


class TripvlogMapStack(cdk.Stack):
    """M5에서 DynamoDB, S3, Lambda, Step Functions, HTTP API, CloudFront를 추가한다."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

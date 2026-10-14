"""CDK 앱 진입점. 리소스는 M5에서 stacks/에 추가한다."""

import aws_cdk as cdk

from infra import config
from infra.stacks.app_stack import TripvlogMapStack

app = cdk.App()
TripvlogMapStack(app, "TripvlogMap", env=cdk.Environment(region=config.REGION))
app.synth()

#!/usr/bin/env bash
# [초안] 코드가 바뀔 때마다: zip을 새로 만들어 9개 함수에 한 번에 반영.
#   git pull && bash infra/deploy/update.sh
set -euo pipefail
P=sgu-clicktotrip

bash infra/deploy/build_zip.sh
aws s3 cp dist/backend.zip s3://$P-config/artifacts/backend.zip

for name in collect claim observe interpret match aggregate api-public cleanup; do
  aws lambda update-function-code --function-name $P-$name \
    --s3-bucket $P-config --s3-key artifacts/backend.zip --query LastModified --output text
done

# 상태 머신 흐름이 바뀌었을 때만 의미가 있지만, 매번 덮어써도 안전하다
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
sed "s/\${account}/$ACCOUNT/g" infra/asl/analyze.asl.json > /tmp/asl.json
aws stepfunctions update-state-machine \
  --state-machine-arn arn:aws:states:ap-northeast-2:$ACCOUNT:stateMachine:$P-analyze \
  --definition file:///tmp/asl.json

echo "✔ 배포 버전: $(git rev-parse --short HEAD)  ← runbook 배포 기록에 적는다"

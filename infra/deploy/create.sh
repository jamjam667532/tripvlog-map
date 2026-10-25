#!/usr/bin/env bash
# [초안] 처음 1번: AWS 리소스 생성. CloudShell(서울 리전)에서 저장소 루트에서 실행.
#   bash infra/deploy/create.sh
# CloudShell은 콘솔 로그인 권한을 그대로 쓰므로 Access Key가 필요 없다.
# 이미 있는 리소스는 건너뛴다(여러 번 실행해도 안전하게).
set -euo pipefail

P=sgu-clicktotrip                       # 결정 0007-4: 모든 이름 접두사
REGION=ap-northeast-2                   # 결정 0007-1: 서울 고정
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ROLE=arn:aws:iam::$ACCOUNT:role/SafeRole-$P   # 결정 0007: 역할은 새로 못 만들고 이것만 쓴다

# ── 1. DynamoDB 테이블 6개 ─────────────────────────────────────────
# 테이블 정의를 손으로 다시 쓰지 않고, 로컬·테스트가 쓰는 정의(shared/repos/tables.py)를 그대로 쓴다.
export JOBS_TABLE=$P-jobs USERS_TABLE=$P-users YOUTUBE_CACHE_TABLE=$P-youtube-cache \
       VIDEO_ANALYSIS_TABLE=$P-video-analysis PLACES_TABLE=$P-places COORD_CACHE_TABLE=$P-coord-cache
pip install -q boto3 pydantic
PYTHONPATH=backend python3 scripts/create_tables.py --region $REGION

# ── 2. S3 버킷 3개 ────────────────────────────────────────────────
for b in web data config; do
  aws s3api head-bucket --bucket $P-$b 2>/dev/null && continue
  aws s3api create-bucket --bucket $P-$b --region $REGION \
    --create-bucket-configuration LocationConstraint=$REGION
  aws s3api put-public-access-block --bucket $P-$b --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
done
echo "▶ 키 파일은 콘솔에서 직접 올린다: s3://$P-config/keys.json (gemini, youtube, places, llm_api_key, llm_base_url)"

# ── 3. Lambda 9개 (공통 zip 하나, 실행 경로만 다름) ───────────────
bash infra/deploy/build_zip.sh            # → dist/backend.zip
aws s3 cp dist/backend.zip s3://$P-config/artifacts/backend.zip   # 50MB 넘으면 S3 경유

ENV="Variables={JOBS_TABLE=$JOBS_TABLE,USERS_TABLE=$USERS_TABLE,YOUTUBE_CACHE_TABLE=$YOUTUBE_CACHE_TABLE,\
VIDEO_ANALYSIS_TABLE=$VIDEO_ANALYSIS_TABLE,PLACES_TABLE=$PLACES_TABLE,COORD_CACHE_TABLE=$COORD_CACHE_TABLE,\
DATA_BUCKET=$P-data,CONFIG_BUCKET=$P-config,CONFIG_KEY=keys.json,\
GEMINI_MODEL=gemini-3.8-flash,BEDROCK_INTERPRETER_MODEL_ID=bedrock-haiku}"   # 비밀값은 넣지 않는다

#        이름        타임아웃(초) 메모리(MB)
FUNCS="  collect     60   512
         claim       30   256
         observe     900  512
         interpret   300  512
         match       120  512
         aggregate   120  512
         api_public  15   256
         cleanup     300  256"
while read -r name timeout mem; do
  fn=$P-${name//_/-}
  aws lambda get-function --function-name $fn >/dev/null 2>&1 && continue
  aws lambda create-function --function-name $fn --runtime python3.12 --role $ROLE \
    --handler functions.$name.handler.handler --timeout $timeout --memory-size $mem \
    --code S3Bucket=$P-config,S3Key=artifacts/backend.zip --environment "$ENV"
done <<< "$FUNCS"

# ── 4. Step Functions ─────────────────────────────────────────────
# ASL 안의 ${account}를 실제 값으로 바꿔 넣는다. 흐름은 tests/integration/pipeline.py와 같다.
SM_ARN=arn:aws:states:$REGION:$ACCOUNT:stateMachine:$P-analyze
if ! aws stepfunctions describe-state-machine --state-machine-arn $SM_ARN >/dev/null 2>&1; then
  sed "s/\${account}/$ACCOUNT/g" infra/asl/analyze.asl.json > /tmp/asl.json
  aws stepfunctions create-state-machine --name $P-analyze --role-arn $ROLE \
    --definition file:///tmp/asl.json --type STANDARD
fi
aws lambda update-function-configuration --function-name $P-api-public \
  --environment "${ENV%\}},STATE_MACHINE_ARN=$SM_ARN}" >/dev/null

# ── 5. API Gateway (HTTP API) ─────────────────────────────────────
# 경로: POST /public/jobs, GET /public/jobs/{jobId} → api-public 함수
API_ID=$(aws apigatewayv2 get-apis --query "Items[?Name=='$P-api'].ApiId" --output text)
if [ -z "$API_ID" ]; then
  API_ID=$(aws apigatewayv2 create-api --name $P-api --protocol-type HTTP \
    --target arn:aws:lambda:$REGION:$ACCOUNT:function:$P-api-public --query ApiId --output text)
  aws lambda add-permission --function-name $P-api-public --statement-id apigw \
    --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:$REGION:$ACCOUNT:$API_ID/*"
fi

# ── 6. 매일 정리 작업 ─────────────────────────────────────────────
aws scheduler get-schedule --name $P-cleanup-daily >/dev/null 2>&1 || \
aws scheduler create-schedule --name $P-cleanup-daily --schedule-expression "cron(0 4 * * ? *)" \
  --flexible-time-window Mode=OFF \
  --target "Arn=arn:aws:lambda:$REGION:$ACCOUNT:function:$P-cleanup,RoleArn=$ROLE"

echo "✔ 완료. API 주소: https://$API_ID.execute-api.$REGION.amazonaws.com"

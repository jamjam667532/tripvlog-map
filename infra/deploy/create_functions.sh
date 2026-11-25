#!/usr/bin/env bash
# Lambda 함수 8개를 만들고(이미 있으면 건너뜀) 환경 변수를 넣는다. AWS CloudShell(서울)에서 실행한다.
#   1) CloudShell 오른쪽 위 "작업 > 파일 업로드"로 backend.zip과 이 파일을 올린다(홈 폴더에 들어간다).
#   2) bash create_functions.sh
# CloudShell은 콘솔 로그인 권한을 쓰므로 Access Key가 필요 없다. 비밀값은 넣지 않는다(결정 0007).
# 환경 변수는 infra/lambda-env.json과 같다(tests/unit/test_deploy_files.py가 확인한다).

P=sgu-clicktotrip
export AWS_DEFAULT_REGION=ap-northeast-2
ZIP=${ZIP:-backend.zip}
[ -f "$ZIP" ] || { echo "$ZIP이 없습니다. CloudShell에 backend.zip을 먼저 올리세요." >&2; exit 1; }

ACCOUNT=$(aws sts get-caller-identity --query Account --output text) || exit 1
ROLE=arn:aws:iam::$ACCOUNT:role/SafeRole-$P
ENV_JSON='{"Variables":{"JOBS_TABLE":"sgu-clicktotrip-jobs","USERS_TABLE":"sgu-clicktotrip-users","YOUTUBE_CACHE_TABLE":"sgu-clicktotrip-youtube-cache","VIDEO_ANALYSIS_TABLE":"sgu-clicktotrip-video-analysis","PLACES_TABLE":"sgu-clicktotrip-places","COORD_CACHE_TABLE":"sgu-clicktotrip-coord-cache","DATA_BUCKET":"sgu-clicktotrip-data","CONFIG_BUCKET":"sgu-clicktotrip-config","CONFIG_KEY":"keys.json","ANALYSIS_VERSION":"v4-seg190","GEMINI_MODELS":"gemini-3.5-flash-lite,gemini-3.1-flash-lite","BEDROCK_INTERPRETER_MODEL_ID":"bedrock-haiku","EMBEDDING_MODEL_ID":"bedrock-titan-embed-v2"}}'
# api_public은 Step Functions를 만들기 전까지 임시 ARN을 쓴다. 만든 뒤 콘솔에서 진짜 값으로 바꾼다.
ENV_API="${ENV_JSON%\}\}},\"STATE_MACHINE_ARN\":\"arn:aws:states:ap-northeast-2:000000000000:stateMachine:placeholder\"}}"

ok=0; fail=0
#    이름        제한 시간(초) 메모리(MB)
while read -r name timeout mem; do
  fn=$P-${name//_/-}
  env=$ENV_JSON; [ "$name" = api_public ] && env=$ENV_API
  if aws lambda get-function --function-name "$fn" >/dev/null 2>&1; then
    echo "· $fn: 이미 있음 → 환경 변수만 넣는다"
  else
    echo "· $fn: 만드는 중"
    if ! aws lambda create-function --function-name "$fn" --runtime python3.12 --architectures x86_64 \
        --role "$ROLE" --handler "functions.$name.handler.handler" --timeout "$timeout" \
        --memory-size "$mem" --zip-file "fileb://$ZIP" --query State --output text; then
      echo "  ✗ $fn 생성 실패 (위 오류 문구를 그대로 전달)"; fail=$((fail+1)); continue
    fi
    # 학교 계정은 만든 직후 몇 초 뒤에 태그를 자동으로 붙이고, 태그가 없는 리소스는 거부한다.
    # 바로 조회하면 AccessDenied가 나므로 태그가 붙을 때까지 기다린다(2026-11-12 첫 실행에서 확인).
    sleep 15
    for _ in 1 2 3 4 5 6; do
      aws lambda wait function-active-v2 --function-name "$fn" 2>/dev/null && break
      sleep 10
    done
  fi
  if aws lambda update-function-configuration --function-name "$fn" --environment "$env" \
      --query LastUpdateStatus --output text >/dev/null; then
    aws lambda wait function-updated-v2 --function-name "$fn"
    echo "  ✓ $fn"; ok=$((ok+1))
  else
    echo "  ✗ $fn 환경 변수 실패"; fail=$((fail+1))
  fi
done <<'LIST'
collect     60  512
claim       30  256
observe     900 512
interpret   300 512
match       120 512
aggregate   120 512
api_public  15  256
cleanup     300 256
LIST

echo "완료: 성공 $ok, 실패 $fail"
aws lambda list-functions --query "Functions[?starts_with(FunctionName, '$P-')].[FunctionName,Handler,Timeout,MemorySize]" --output table

#!/usr/bin/env bash
# M8 로그인 배포 (결정 0007-2, 0010, 0011). AWS CloudShell(서울)에서 실행한다.
#   1) CloudShell에 새 backend.zip과 이 파일을 올린다(올리기 전에 rm -f backend.zip)
#   2) bash m8_setup.sh <Google OAuth Client ID>
# 하는 일: 기존 Lambda 코드·환경 변수 갱신 → api-jobs·api-me 생성 → API 호출 권한 →
#          JWT Authorizer(Google ID 토큰) → 로그인 경로 8개 → CORS.
# 여러 번 실행해도 된다(있는 것은 건너뛰거나 갱신한다). 비밀값은 넣지 않는다.

P=sgu-clicktotrip
export AWS_DEFAULT_REGION=ap-northeast-2
CLIENT_ID=${1:?Google OAuth Client ID가 필요합니다}
API_ID=${API_ID:-dp4nohrcak}
WEB=${WEB:-https://d1iehbeyllkxs5.cloudfront.net}
ZIP=${ZIP:-backend.zip}
EMBEDDING=${EMBEDDING:-bedrock-titan-embed-v2}
ISSUER=https://accounts.google.com  # TODO(verify, 결정 0007-2): 실제 토큰의 iss

[ -f "$ZIP" ] || { echo "$ZIP이 없습니다." >&2; exit 1; }
ACCOUNT=$(aws sts get-caller-identity --query Account --output text) || exit 1
ROLE=arn:aws:iam::$ACCOUNT:role/SafeRole-$P
fail=0

with_env() {  # 함수 환경 변수에 KEY=VALUE를 더한 JSON을 출력한다(기존 값 유지)
  aws lambda get-function-configuration --function-name "$1" --query Environment --output json |
    python3 -c "import json,sys;e=json.load(sys.stdin) or {};v=e.setdefault('Variables',{});v.update(dict(a.split('=',1) for a in sys.argv[1:]));print(json.dumps({'Variables':v}))" "${@:2}"
}

echo "── 1. 기존 Lambda: 새 코드 + EMBEDDING_MODEL_ID"
for f in collect claim observe interpret match aggregate api-public cleanup; do
  fn=$P-$f
  if aws lambda update-function-code --function-name "$fn" --zip-file "fileb://$ZIP" --query CodeSize --output text >/dev/null &&
     aws lambda wait function-updated-v2 --function-name "$fn" &&
     aws lambda update-function-configuration --function-name "$fn" \
       --environment "$(with_env "$fn" EMBEDDING_MODEL_ID=$EMBEDDING)" --query LastUpdateStatus --output text >/dev/null &&
     aws lambda wait function-updated-v2 --function-name "$fn"; then
    echo "  ✓ $fn"
  else
    echo "  ✗ $fn"; fail=$((fail+1))
  fi
done

echo "── 2. 새 Lambda: api-jobs, api-me"
BASE_ENV=$(with_env $P-api-public EMBEDDING_MODEL_ID=$EMBEDDING)  # STATE_MACHINE_ARN 포함
#    이름      제한 시간 메모리   (api-me: 유튜브 연결이 YouTube·Bedrock·임베딩을 부른다. API Gateway 30초 안)
while read -r name timeout mem; do
  fn=$P-${name//_/-}
  if aws lambda get-function --function-name "$fn" >/dev/null 2>&1; then
    echo "  · $fn: 이미 있음 → 코드만 갱신"
    aws lambda update-function-code --function-name "$fn" --zip-file "fileb://$ZIP" --query CodeSize --output text >/dev/null
  else
    aws lambda create-function --function-name "$fn" --runtime python3.12 --architectures x86_64 \
      --role "$ROLE" --handler "functions.$name.handler.handler" --timeout "$timeout" \
      --memory-size "$mem" --zip-file "fileb://$ZIP" --environment "$BASE_ENV" \
      --query State --output text >/dev/null || { echo "  ✗ $fn 생성 실패"; fail=$((fail+1)); continue; }
    sleep 20  # 학교 계정은 태그를 몇 초 뒤에 붙이고, 태그 없는 리소스는 거부한다
    for _ in 1 2 3 4 5 6; do aws lambda wait function-active-v2 --function-name "$fn" 2>/dev/null && break; sleep 10; done
  fi
  echo "  ✓ $fn"
done <<'LIST'
api_jobs 15 256
api_me   29 512
LIST

echo "── 3. API Gateway가 Lambda를 부를 권한"
for f in api-jobs api-me; do
  aws lambda add-permission --function-name $P-$f --statement-id apigw-invoke \
    --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:ap-northeast-2:$ACCOUNT:$API_ID/*" >/dev/null 2>&1 \
    && echo "  ✓ $P-$f" || echo "  · $P-$f: 이미 있음(또는 거부 — 아래 확인에서 403이면 이 단계 문제)"
done

echo "── 4. JWT Authorizer (Google ID 토큰)"
AUTH=$(aws apigatewayv2 get-authorizers --api-id "$API_ID" --query "Items[?Name=='google-id-token'].AuthorizerId" --output text)
if [ -z "$AUTH" ] || [ "$AUTH" = None ]; then
  AUTH=$(aws apigatewayv2 create-authorizer --api-id "$API_ID" --name google-id-token \
    --authorizer-type JWT --identity-source '$request.header.Authorization' \
    --jwt-configuration "Audience=$CLIENT_ID,Issuer=$ISSUER" --query AuthorizerId --output text) \
    || { echo "  ✗ Authorizer 생성 실패"; exit 1; }
fi
echo "  ✓ $AUTH (audience = Client ID, issuer = $ISSUER)"

echo "── 5. 로그인 경로"
integration() {  # 함수별 통합 ID(없으면 만든다)
  local uri=arn:aws:lambda:ap-northeast-2:$ACCOUNT:function:$P-$1
  local id
  id=$(aws apigatewayv2 get-integrations --api-id "$API_ID" --query "Items[?IntegrationUri=='$uri'].IntegrationId | [0]" --output text)
  if [ -z "$id" ] || [ "$id" = None ]; then
    id=$(aws apigatewayv2 create-integration --api-id "$API_ID" --integration-type AWS_PROXY \
      --integration-uri "$uri" --payload-format-version 2.0 --timeout-in-millis 29000 \
      --query IntegrationId --output text)
  fi
  echo "$id"
}
JOBS=$(integration api-jobs); ME=$(integration api-me)
EXISTING=$(aws apigatewayv2 get-routes --api-id "$API_ID" --query 'Items[].RouteKey' --output json)
has_route() { python3 -c "import json,sys;sys.exit(0 if sys.argv[2] in json.loads(sys.argv[1]) else 1)" "$EXISTING" "$1"; }
while read -r method path target; do
  key="$method $path"
  if has_route "$key"; then echo "  · $key: 이미 있음"; continue; fi
  integ=$JOBS; [ "$target" = me ] && integ=$ME
  aws apigatewayv2 create-route --api-id "$API_ID" --route-key "$key" --target "integrations/$integ" \
    --authorization-type JWT --authorizer-id "$AUTH" --query RouteKey --output text >/dev/null \
    && echo "  ✓ $key" || { echo "  ✗ $key"; fail=$((fail+1)); }
done <<'ROUTES'
POST /jobs jobs
GET /jobs/{jobId} jobs
POST /jobs/{jobId}/rerank jobs
GET /me/preferences me
PATCH /me/preferences me
POST /me/youtube/import me
POST /me/youtube/confirm me
DELETE /me/youtube/connection me
ROUTES

echo "── 6. CORS (로그인 헤더·메서드 추가)"
aws apigatewayv2 update-api --api-id "$API_ID" --cors-configuration \
  "{\"AllowOrigins\":[\"$WEB\",\"http://localhost:5173\"],\"AllowHeaders\":[\"content-type\",\"x-guest-access-token\",\"authorization\",\"x-google-access-token\"],\"AllowMethods\":[\"GET\",\"POST\",\"PATCH\",\"DELETE\",\"OPTIONS\"],\"MaxAge\":300}" \
  --query 'CorsConfiguration.AllowHeaders' --output text >/dev/null && echo "  ✓ CORS" || { echo "  ✗ CORS"; fail=$((fail+1)); }

echo "── 확인"
API=https://$API_ID.execute-api.ap-northeast-2.amazonaws.com
printf '  토큰 없이 /me/preferences → '; curl -s -o /dev/null -w '%{http_code} (401이면 Authorizer 동작)\n' "$API/me/preferences"
printf '  게스트 경로 그대로 → '; curl -s -o /dev/null -w '%{http_code} (404면 정상)\n' "$API/public/jobs/00000000-0000-4000-8000-000000000000" -H 'x-guest-access-token: t'
echo "완료: 실패 $fail"

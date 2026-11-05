# AWS 백엔드 콘솔 세팅 안내

> 순서대로 하면 된다. 콘솔 리전은 **서울(ap-northeast-2)**, 이름은 모두 `sgu-clicktotrip-`로 시작한다. 근거: 결정 0007.
> 전체 명세는 `docs/deploy-runbook.md`. 명령은 브랜치 `feature/aws-first-deploy`의 저장소 루트에서 실행한다.
> 프론트(S3 + CloudFront)는 백엔드 시험이 끝난 뒤에 한다.

## 1. 버킷·키·테이블

**S3 버킷 2개** (퍼블릭 액세스 모두 차단, 나머지 기본값): `sgu-clicktotrip-data`, `sgu-clicktotrip-config`

**keys.json** 만들어서 올리기. 값은 화면에 나오지 않는다.

```bash
uv run python scripts/make_keys_json.py /Users/m2/y4s2prjct/experiments/.env
```

`~/sgu-clicktotrip-keys.json`이 생긴다. `sgu-clicktotrip-config`에 **이름을 `keys.json`으로 바꿔** 올리고, 올린 뒤 로컬 파일은 지운다. 화면 공유 중에 열지 않는다.

**DynamoDB 테이블 6개** (용량 모드 **온디맨드**, 키는 모두 문자열)

| 테이블 | 파티션 키 | 정렬 키 | 추가 설정 |
| --- | --- | --- | --- |
| `sgu-clicktotrip-jobs` | `jobId` | - | GSI `requestId-index`: 파티션 `requestId`, 프로젝션 **키만** |
| `sgu-clicktotrip-video-analysis` | `videoId` | `analysisVersion` | - |
| `sgu-clicktotrip-places` | `placeId` | `sk` | GSI `videoId-index`: 파티션 `videoId`, 정렬 `evidenceKey`, 프로젝션 **모두** |
| `sgu-clicktotrip-youtube-cache` | `pk` | `sk` | TTL 속성 `expiresAt` |
| `sgu-clicktotrip-coord-cache` | `placeId` | - | TTL 속성 `expiresAt` |
| `sgu-clicktotrip-users` | `userId` | - | - |

## 2. Lambda 8개

zip 만들기: `bash infra/deploy/build_zip.sh` → `dist/backend.zip` (약 10MB, 콘솔에서 바로 올릴 수 있다).

**함수 생성 > 새로 작성**. 공통 값: 런타임 **Python 3.12**, 아키텍처 **x86_64**(zip이 이 형식이다), 실행 역할 **기존 역할** `SafeRole-sgu-clicktotrip`.

| 함수 이름 | 핸들러 | 제한 시간 | 메모리 |
| --- | --- | --- | --- |
| `sgu-clicktotrip-collect` | `functions.collect.handler.handler` | 1분 | 512MB |
| `sgu-clicktotrip-claim` | `functions.claim.handler.handler` | 30초 | 256MB |
| `sgu-clicktotrip-observe` | `functions.observe.handler.handler` | 15분 | 512MB |
| `sgu-clicktotrip-interpret` | `functions.interpret.handler.handler` | 5분 | 512MB |
| `sgu-clicktotrip-match` | `functions.match.handler.handler` | 2분 | 512MB |
| `sgu-clicktotrip-aggregate` | `functions.aggregate.handler.handler` | 2분 | 512MB |
| `sgu-clicktotrip-api-public` | `functions.api_public.handler.handler` | 15초 | 256MB |
| `sgu-clicktotrip-cleanup` | `functions.cleanup.handler.handler` | 5분 | 256MB |

함수마다 할 일:

1. **코드 > 업로드 > .zip 파일**로 `dist/backend.zip`을 올린다.
2. **코드 > 런타임 설정 > 편집**에서 핸들러를 표의 값으로 바꾼다. 기본값 `lambda_function.lambda_handler`로 두면 실행되지 않는다.
3. **구성 > 일반 구성**에서 제한 시간과 메모리를 표대로 바꾼다.
4. **구성 > 환경 변수**에 아래 값을 넣는다. 원본은 `infra/lambda-env.json`이고 비밀값은 없다.

| 이름 | 값 |
| --- | --- |
| `JOBS_TABLE` | `sgu-clicktotrip-jobs` |
| `USERS_TABLE` | `sgu-clicktotrip-users` |
| `YOUTUBE_CACHE_TABLE` | `sgu-clicktotrip-youtube-cache` |
| `VIDEO_ANALYSIS_TABLE` | `sgu-clicktotrip-video-analysis` |
| `PLACES_TABLE` | `sgu-clicktotrip-places` |
| `COORD_CACHE_TABLE` | `sgu-clicktotrip-coord-cache` |
| `DATA_BUCKET` | `sgu-clicktotrip-data` |
| `CONFIG_BUCKET` | `sgu-clicktotrip-config` |
| `CONFIG_KEY` | `keys.json` |
| `ANALYSIS_VERSION` | `v2-seg190` |
| `GEMINI_MODELS` | `gemini-3.5-flash-lite,gemini-3.1-flash-lite` |
| `BEDROCK_INTERPRETER_MODEL_ID` | `bedrock-haiku` |

`sgu-clicktotrip-api-public`에는 하나 더 넣는다. Step Functions를 만들기 전까지는 임시 값이다.

| 이름 | 값 |
| --- | --- |
| `STATE_MACHINE_ARN` | `arn:aws:states:ap-northeast-2:000000000000:stateMachine:placeholder` |

8개를 반복하기 번거로우면 함수를 만든 뒤 CloudShell에서 환경 변수만 한 번에 넣을 수 있다(저장소의 `infra/lambda-env.json`을 CloudShell에 올려서):

```bash
for f in collect claim observe interpret match aggregate cleanup; do
  aws lambda update-function-configuration --function-name sgu-clicktotrip-$f --environment file://lambda-env.json
done
```

## 3. Lambda 시험 실행

유료 API를 부르지 않는 시험이다. 콘솔의 **테스트** 탭에 이벤트를 넣고 실행한다.

**① `sgu-clicktotrip-api-public`** (zip, 환경 변수, DynamoDB 권한 확인)

```json
{"routeKey": "GET /public/jobs/{jobId}", "pathParameters": {"jobId": "00000000-0000-4000-8000-000000000000"}, "headers": {"x-guest-access-token": "test"}}
```

**통과:** `statusCode`가 **404**. 없는 작업이니 이것이 정상이다. `Runtime.ImportModuleError`면 핸들러 경로나 아키텍처를, 500이면 로그의 DynamoDB 오류를 본다.

**② `sgu-clicktotrip-collect`** (keys.json 읽기 확인)

```json
{"jobId": "00000000-0000-4000-8000-000000000000"}
```

**통과:** 오류 이름이 **`JobNotFound`**다. 실행은 실패로 표시되지만 정상이다. 키를 먼저 읽은 뒤 작업을 찾으므로 키 읽기는 성공한 것이고, YouTube는 부르지 않는다. **실패:** `AccessDenied`·`NoSuchKey`·`NoSuchBucket`은 설정 버킷·권한 문제, `secret ... is not in the keys file`은 keys.json 내용 문제다.

**확인 후:** CloudWatch 로그에 키 값이 보이지 않는지 본다.

## 4. Step Functions

정의 파일의 `${account}`를 계정 번호(콘솔 오른쪽 위 12자리)로 바꿔 클립보드에 복사한다.

```bash
sed 's/${account}/123456789012/g' infra/asl/analyze.asl.json | pbcopy
```

**상태 머신 생성 > 코드로 작성**에 붙여 넣는다. 이름 `sgu-clicktotrip-analyze`, 유형 **Standard**, 실행 역할 **기존 역할** `SafeRole-sgu-clicktotrip`.

만든 뒤 ARN을 복사해 `sgu-clicktotrip-api-public`의 `STATE_MACHINE_ARN`을 **진짜 값으로 바꾼다.**

**확인:** 저장이 된다. 역할 권한 오류가 나면 오류 문구를 담당자에게 전달한다. 실행 시험은 6번에서 한다.

## 5. API Gateway

**API 생성 > HTTP API**. 이름 `sgu-clicktotrip-api`, 통합은 Lambda `sgu-clicktotrip-api-public`(페이로드 형식 **2.0**).

| 메서드 | 경로 |
| --- | --- |
| POST | `/public/jobs` |
| GET | `/public/jobs/{jobId}` |

스테이지는 `$default`, 자동 배포 켬. 만든 뒤 **스로틀링**을 켠다(제안: 속도 5, 버스트 10). 공개 API를 막는 장치가 이것뿐이다. 호출 URL을 복사해 둔다.

**확인:** 아래가 404를 돌려준다. 500이나 403이면 Lambda 호출 권한을 본다.

```bash
API=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
curl -i "$API/public/jobs/00000000-0000-4000-8000-000000000000" -H 'x-guest-access-token: test'
```

## 6. 전체 시험 (실제 API 호출)

**여기서부터 실제 키를 쓴다.** YouTube·Gemini·Places·게이트웨이 한도를 소모하므로 한 건씩 한다. 영상을 한 줄로 처리해서(Map 동시성 1) 끝까지 **10분 안팎**을 예상한다(추정, 첫 실행으로 잰다).

```bash
curl -s -X POST "$API/public/jobs" -H 'content-type: application/json' \
  -d "{\"requestId\": \"$(uuidgen | tr A-Z a-z)\", \"destination\": \"오사카\"}"
```

202와 함께 `jobId`, `guestAccessToken`이 온다. 토큰은 이때 한 번만 나온다.

```bash
curl -s "$API/public/jobs/<jobId>" -H 'x-guest-access-token: <토큰>'
```

**통과:** `status`가 `QUEUED → RUNNING → SUCCEEDED` 또는 `PARTIAL`로 바뀌고 결과에 장소가 있다. Step Functions 콘솔의 실행 그래프에서 단계별 성공을 본다. 이때 처음으로 확인되는 것을 기록한다.

- [ ] Lambda(서울)에서 학교 게이트웨이로 나가는 연결 (interpret 단계)
- [ ] 영상별 소요 시간, 제한 시간(observe 15분) 안에 드는지
- [ ] 같은 도시를 다시 요청했을 때 분석을 건너뛰는지(REUSE)
- [ ] CloudWatch 로그에 키·토큰·좌표·Places 원문이 없는지

**실패하면:** 실행 그래프에서 빨간 단계를 눌러 오류 이름과 그 함수의 CloudWatch 로그를 확인한다.

## 막히면 전달할 것

단계 번호, 오류 문구 전체, 함수 이름. 키 값과 `keys.json` 내용은 보내지 않는다.

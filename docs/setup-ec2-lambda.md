# EC2·Lambda 콘솔 세팅 안내

> 순서대로 하면 된다. 콘솔 리전은 **서울(ap-northeast-2)**, 이름은 모두 `sgu-clicktotrip-`로 시작한다. 근거: 결정 0007, 0009.
> 전체 명세는 `docs/deploy-runbook.md`. 저장소 루트는 브랜치 `feature/aws-first-deploy`.

## 1. EC2 (프론트 서버)

**EC2 > 인스턴스 시작**

| 항목 | 값 |
| --- | --- |
| 이름 | `sgu-clicktotrip-web` |
| AMI | Amazon Linux 2023 (64비트 x86) |
| 유형 | `t3.micro` |
| 키 페어 | 새로 만들기 `sgu-clicktotrip-key`, RSA, `.pem`. 내려받은 파일은 저장소 밖에 두고 `chmod 400` |
| 네트워크 | 기본 VPC, 공인 IP 자동 할당 **켬** |
| 보안 그룹 | 새로 만들기 `sgu-clicktotrip-web`. HTTP 80은 모든 곳, SSH 22는 **내 IP** |
| 스토리지 | 기본값(8GB gp3) |
| IAM 인스턴스 프로파일 | **없음** |
| 고급 > 사용자 데이터 | `infra/ec2/user-data.sh` 내용 전체 |

**확인:** 2~3분 뒤 `http://<공인 IP>`에 "EC2 준비 완료"가 보인다.

- **만들기가 거부되면** 여기서 멈춘다. 계정 회신의 허용 목록에 EC2가 없어서 담당자에게 물어야 한다. 오류 문구를 그대로 전달한다.
- 안 쓸 때는 **중지**한다. 다시 켜면 IP가 바뀐다.

## 2. Lambda를 만들기 전에: 버킷·키·테이블

Lambda 시험 실행에 필요해서 먼저 만든다.

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

## 3. Lambda 8개

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

## 4. Lambda 시험 실행

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

## 5. 다음 단계

Step Functions(`infra/asl/analyze.asl.json`) → API Gateway → `infra/ec2/deploy_frontend.sh`로 화면 연결. `docs/deploy-runbook.md` §5~§7.

## 막히면 전달할 것

단계 번호, 오류 문구 전체, 함수 이름. 키 값과 `keys.json` 내용은 보내지 않는다.

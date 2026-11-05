# AWS 배포 명세서 (M5, 학교 계정)

> 상태: **초안** (C1~C3 코드 완료, 콘솔 작업 전) · 기준일 2026-11-05 · 근거: 결정 0007(계정 제약), 0008(실시간 분석), implementation-spec §2·§4·§11
> 대상: 배포를 맡는 사람(남현우)과 코드를 고치는 에이전트. 값이 사람 확인이 필요한 곳은 **[확인]**으로 표시했다.
> 이 문서는 명세다. 리소스는 사람이 콘솔에서 직접 만든다(결정 0007-5). `infra/deploy/`의 CloudShell 스크립트는 보관만 한다.

## 1. 목표와 현재 상태

- **목표:** 학교 계정(서울)에 1단계(게스트 `/public/*`)를 올려 spec M5 "학교 계정 최소 배포 성공"과 M6 "배포 환경에서 fixture 목적지 결과 표시"를 가능하게 한다. 로그인(M8)은 범위 밖이다.
- **지금 상태:** 파이프라인은 로컬 서버(`backend/local/server.py`)에서 실제 키로 1건 돌아갔다(영상 5/5, 18곳). **그러나 Lambda로는 아직 올릴 수 없다.** §2의 코드 선행 작업이 남아 있다.

## 2. 배포 전에 코드에서 먼저 끝낼 것

| # | 할 일 | 위치 | 이유 | 완료 조건 |
| --- | --- | --- | --- | --- |
| ✅ C1 | 서버 키를 SSM 대신 설정 버킷 `keys.json`에서 읽는다. `Settings`의 `*_key_param`을 `CONFIG_BUCKET`·`CONFIG_KEY`로 바꾸고, collect·match·observe의 `get_secret` 호출을 새 이름으로 바꾼다 | `shared/clients/secrets.py`, `shared/settings.py`, `functions/{collect,match,observe}/handler.py` | SSM 불허(결정 0007-3). 지금 코드는 `boto3.client("ssm")`을 부른다 | moto S3 테스트 통과, 로그에 값·JSON 없음 |
| ✅ C2 | interpret 핸들러를 `BedrockConverseInterpreter`(boto3 직접 호출) 대신 학교 게이트웨이 `GatewayChatInterpreter`로 바꾼다. 키·주소는 `keys.json`의 `llm_api_key`·`llm_base_url`. 모델은 별칭 `bedrock-haiku` | `functions/interpret/handler.py` (구성은 `backend/local/server.py`가 이미 쓰는 것을 따른다) | 계정은 Bedrock을 게이트웨이로만 쓴다(결정 0007-1). `ChunkedInterpreter`는 유지 | 단위 테스트 통과(가짜 게이트웨이) |
| ✅ C3 | Step Functions ASL 작성 | `infra/asl/analyze.asl.json` | §6 흐름 명세대로 | `tests/integration/pipeline.py`와 같은 순서·이벤트 |
| C4 | **Gemini 요청 제한을 Lambda 전체에서 지키는 방법 정하기** | §9-A | `RateLimiter`는 프로세스 안에서만 센다. Lambda는 동시에 실행되면 환경이 따로라서 영상 5개를 병렬로 돌리면 모델별 분당 14회를 환경마다 따로 센다 | 결정 확정 후 구현 |
| C5 | Gemini 하루 예산 카운터 | 아직 없음. 지금은 YouTube 검색 카운터(`take_search_quota`)만 있다 | 결정 0006-5의 "하루 18"은 영상 통째로 보내던 때 기준이다. 구간 방식은 영상당 요청이 훨씬 많다 | **[확인]** 하루 상한 값 |
| C6 | CDK 앱 삭제, `infra/config.py` 갱신(리전 `us-east-1` → 서울, 모델 ID 항목은 별칭으로) | `infra/` | 결정 0007-5·0007 영향 표 | 값 목록만 남음 |
| C7 | 배포용 `ANALYSIS_VERSION` 확정 | 환경 변수 | 이 값이 바뀌면 **저장된 분석이 전부 재사용되지 않는다**(비용). 값을 고정하고 올릴 때는 결정 기록을 남긴다 | **[확인]** 제안: `v2-seg190` (발표 8쪽 예시와 같음) |

**C1~C3는 브랜치 `feature/aws-first-deploy`에서 끝났다**(pytest 302개, ruff·mypy 통과, ASL 정합성 테스트 10개 포함). 남은 C4~C7은 값·결정이 필요하다. **C4가 병렬 분석의 병목이다.** 첫 배포는 Map 동시성 1(영상 한 줄)로 시작한다.

## 3. 학교 계정 제약 (결정 0007)

| 구분 | 내용 |
| --- | --- |
| 허용 | Lambda, ECR, Step Functions, API Gateway, DynamoDB, S3, CloudFront(WAF 끔), EventBridge Scheduler, CloudWatch. Bedrock은 US 리전 |
| 불허 | Cognito, SSM Parameter Store. 목록에 CloudFormation·IAM·EC2도 없다 |
| 리전 | ap-northeast-2(서울) 고정. Bedrock은 게이트웨이가 정한다 |
| 이름 | 모든 리소스 `sgu-clicktotrip-` 접두사 |
| 역할 | 새로 못 만든다. Lambda·Step Functions·Scheduler 모두 `SafeRole-sgu-clicktotrip` |
| 자격증명 | Access Key 불가. **Lambda 환경 변수에 비밀값 금지** |
| 기타 | 리소스 생성 직후 약 5초 지연. 두 사람이 같은 리소스를 공유한다 → 배포는 한 번에 한 사람 |

## 4. 리소스 명세

### 4.1 DynamoDB (온디맨드, 6개)

| 테이블 | PK | SK | GSI | TTL |
| --- | --- | --- | --- | --- |
| `sgu-clicktotrip-jobs` | `jobId` | - | `requestId-index` (PK `requestId`) | - |
| `sgu-clicktotrip-video-analysis` | `videoId` | `analysisVersion` | - | - |
| `sgu-clicktotrip-places` | `placeId` | `sk` | `videoId-index` (PK `videoId`, SK `evidenceKey`) | - |
| `sgu-clicktotrip-youtube-cache` | `pk` | `sk` | - | `expiresAt` |
| `sgu-clicktotrip-coord-cache` | `placeId` | - | - | `expiresAt` |
| `sgu-clicktotrip-users` | `userId` | - | - | - (M8, 지금은 만들어 두기만) |

모든 키는 문자열이다. TTL은 보조 수단이고 만료 삭제는 cleanup이 한다. 정의의 원본은 `backend/shared/repos/tables.py`다.

### 4.2 S3 (3개, 전부 퍼블릭 차단)

| 버킷 | 용도 | 비고 |
| --- | --- | --- |
| `sgu-clicktotrip-web` | 정적 프론트 | CloudFront OAC로만 읽음 |
| `sgu-clicktotrip-data` | 분석·결과 JSON | Lambda(SafeRole)만 접근. 키 규칙은 코드가 정한다(`shared/repos/blobs.py`) |
| `sgu-clicktotrip-config` | `keys.json` | SSE-S3, SafeRole만 `GetObject`. 웹·데이터 버킷과 분리 |

`keys.json` 형식(키 이름만, **값은 문서·채팅·로그·커밋에 쓰지 않는다**): `gemini`, `youtube`, `places`, `llm_api_key`, `llm_base_url`. 값은 DM으로 받은 것을 사람이 콘솔에서 직접 올린다.

### 4.3 Lambda (8개 배포, `api_jobs`·`api_me`는 M8이라 제외)

공통 zip 하나, 핸들러 경로만 다르다(`functions.<name>.handler.handler`). Python 3.12, 역할 `SafeRole-sgu-clicktotrip`. 이름은 `sgu-clicktotrip-<name>`(밑줄은 하이픈).

| 함수 | 타임아웃(초) | 메모리(MB) | 쓰는 외부 | 비고 |
| --- | --- | --- | --- | --- |
| collect | 60 | 512 | YouTube | |
| claim | 30 | 256 | - | |
| observe | 900 | 512 | Gemini | 최대 타임아웃. 구간이 줄을 서서 길어질 수 있다 |
| interpret | 300 | 512 | 게이트웨이 | |
| match | 120 | 512 | Places | |
| aggregate | 120 | 512 | - | |
| api_public | 15 | 256 | Step Functions | 환경 변수에 `STATE_MACHINE_ARN` 추가 |
| cleanup | 300 | 256 | YouTube | **아직 껍데기.** 구현 전에는 스케줄을 켜지 않는다 |

타임아웃·메모리는 `infra/deploy/create.sh` 초안의 값이고 **측정한 값이 아니다.** 첫 실행 뒤 CloudWatch의 실제 사용량으로 조정한다.

### 4.4 환경 변수 (비밀값 없음)

| 이름 | 값(제안) | 비고 |
| --- | --- | --- |
| `JOBS_TABLE` 등 테이블 6개 | §4.1의 이름 | |
| `DATA_BUCKET` | `sgu-clicktotrip-data` | |
| `CONFIG_BUCKET`, `CONFIG_KEY` | `sgu-clicktotrip-config`, `keys.json` | C1 이후 |
| `ANALYSIS_VERSION` | C7 | |
| `MAX_VIDEOS_PER_JOB`, `SPARE_VIDEOS_PER_JOB`, `MAX_REPLACEMENTS_PER_JOB` | 5, 3, 1 | |
| `COORD_TTL_DAYS`, `YOUTUBE_CACHE_TTL_DAYS` | 25, 25 | |
| `LEASE_SEC`, `MAX_CLAIM_WAITS` | 900, 20 | |
| `DAILY_SEARCH_LIMIT` | 90 | YouTube 검색 하루 상한 |
| `GEMINI_MODELS` | `gemini-3.5-flash-lite,gemini-3.1-flash-lite` | 선호 순. 실험으로 정한 값 |
| `GEMINI_SEGMENT_SEC`, `GEMINI_FPS`, `GEMINI_RPM` | 190, 0.5, 14 | |
| `GEMINI_MEDIA_RESOLUTION` | `MEDIA_RESOLUTION_LOW` | |
| `BEDROCK_INTERPRETER_MODEL_ID` | `bedrock-haiku` | 게이트웨이 별칭 |
| `STATE_MACHINE_ARN` | 만든 뒤 입력 | api_public만 |

`create.sh`의 `GEMINI_MODEL=gemini-3.8-flash`는 오래된 값이다. 쓰지 않는다.

### 4.5 API Gateway (HTTP API `sgu-clicktotrip-api`)

| 경로 | 대상 | 인증 |
| --- | --- | --- |
| `POST /public/jobs` | api_public | 없음 |
| `GET /public/jobs/{jobId}` | api_public | 헤더 `x-guest-access-token` |

- 스테이지 스로틀을 켠다(WAF를 못 쓰므로 공개 API 보호는 이것과 일일 카운터뿐이다). **[확인]** rate·burst 값. 제안: rate 5/s, burst 10.
- CORS는 CloudFront로 같은 도메인을 쓰면 필요 없다.

### 4.6 CloudFront

- 기본 동작: S3(`sgu-clicktotrip-web`, OAC). SPA라서 403/404를 `/index.html`로 돌린다.
- `/api/*` 동작: API Gateway 오리진, **캐시 끔**, 헤더 `x-guest-access-token`을 오리진에 전달, 경로 접두사 `/api`를 떼고 넘긴다(또는 API 쪽 경로를 맞춘다).
- WAF는 끈다. HTTPS 인증서는 CloudFront 기본 도메인을 쓴다.
- **프론트 빌드 환경 변수(남현우 확인):** `VITE_API_BASE`가 없으면 프론트는 **가짜 API로 동작한다**(`frontend/src/api.ts`). 배포 빌드에는 반드시 넣는다. `VITE_GOOGLE_MAPS_API_KEY`(도메인 제한)와 `VITE_GOOGLE_MAPS_MAP_ID`도 필요하다.

### 4.7 EventBridge Scheduler·CloudWatch

- `sgu-clicktotrip-cleanup-daily`: 하루 1회, cleanup 구현 뒤에만 활성화.
- 로그 그룹은 Lambda마다 자동 생성된다. **보존 기간을 정한다**(제안 14일). 로그에 토큰·키·Places 원문·좌표가 남지 않아야 한다.

## 5. Step Functions 흐름 명세 (ASL 작성 기준, C3)

이름 `sgu-clicktotrip-analyze`, 유형 **Standard**, 역할 SafeRole. 실행 이름은 `jobId`. 정의 안의 `${account}`는 계정 번호로 바꿔 붙여 넣는다. 원본 흐름은 `backend/shared/schemas/events.py`와 `backend/tests/integration/pipeline.py`다.

1. **collect** 입력 `{jobId}` → 출력 `{jobId, videoRefs[]}`
2. **Inline Map** `videoRefs` 항목마다
   1. **claim** → `decision`이 `REUSE`면 이 항목 끝, `WAIT`면 30초 대기 후 claim 다시, `ANALYZE`면 계속
   2. **observe** → **interpret** → **match**
   3. 어느 단계든 실패하면 Catch → **claim(action=fail)**로 실패 기록. 다른 영상은 계속한다
   4. Retry는 Lambda 서비스 오류에만 건다. 게이트웨이 `BUDGET_EXCEEDED`·설정 오류(401, 모델 없음)는 재시도하지 않는다
3. **aggregate(action=replace)** → 대체 영상이 있으면 그 영상으로 2번 흐름, 없으면 다음
4. **aggregate** (기본 action) → 결과 JSON 저장, 상태 종료
- 단계 사이에는 **ID·상태·S3 키만** 넘긴다(256 KiB 제한).
- Map `MaxConcurrency`는 §9-A 결정에 따른다.
- 영상 하나가 끝날 때(REUSE·성공·실패)마다 `aggregate(action=snapshot)`을 부른다. 지도 중간 표시용이고, 실패해도 분석은 멈추지 않는다(`SnapshotSkipped`).

**ASL의 알려진 한계**
1. **collect가 실패하면 Jobs 상태가 바뀌지 않는다.** 실행은 `CollectFailed`로 끝나지만 조회는 계속 진행 중으로 보인다. 작업을 FAILED로 바꾸는 동작이 지금 핸들러에 없다. 추가 방법(collect 안에서 처리, 또는 aggregate 동작 추가)은 다음 작업이다.
2. Snapshot은 같은 `live.json`을 쓴다. 로컬 서버는 락으로 막는다. Map 동시성이 1인 지금은 겹치지 않지만, §9-A로 병렬을 켜면 겹칠 수 있다.
3. Retry는 Lambda 서비스 오류에만 건다. 게이트웨이 `BUDGET_EXCEEDED`·설정 오류는 곧바로 영상 실패로 기록된다(결정 0007-1).
4. Task 타임아웃은 Lambda 타임아웃보다 조금 길게(observe 930초 등) 잡았다. 실측 후 조정한다.

## 6. 콘솔 작업 순서

배포 담당 1명이 순서대로 한다. 각 단계 끝의 **확인**을 통과한 뒤 다음으로 간다. 리소스를 만든 직후 약 5초는 기다린다.

- [ ] **0. 사전 확인:** 콘솔 리전이 서울인지, `SafeRole-sgu-clicktotrip`이 보이는지. **확인:** 역할 ARN을 메모한다.
- [ ] **1. S3 버킷 3개** (§4.2, 퍼블릭 차단). **확인:** 세 버킷 모두 퍼블릭 액세스 차단 상태.
- [ ] **2. `keys.json` 업로드** (설정 버킷). 값은 화면 공유·캡처에 보이지 않게 한다. **확인:** 객체가 있고, 버킷 정책이 SafeRole만 허용.
- [ ] **3. DynamoDB 6개** (§4.1, 온디맨드, TTL 2개). **확인:** GSI 이름과 TTL 속성 이름이 표와 같다.
- [ ] **4. zip 만들기:** 저장소 루트에서 `bash infra/deploy/build_zip.sh`(uv 필요) → `dist/backend.zip`. **측정값(2026-11-05): zip 10MB, 풀린 크기 36MB**로 한도(50MB·250MB) 안이다. 콘솔 업로드 한도를 넘지 않으면 직접 올리고, 넘으면 S3에 올려 그 경로로 지정한다. 리눅스용 바이너리로 받으므로 맥에서 직접 실행해 볼 수는 없다.
- [ ] **5. Lambda 8개** (§4.3, §4.4). **확인:** 함수마다 핸들러 경로 오타가 없는지, 환경 변수에 비밀값이 없는지.
- [ ] **6. 함수 단독 테스트:** claim·collect를 콘솔의 테스트 이벤트로 실행한다(fixture 목적지). **확인:** 오류 없이 JSON을 돌려주고, 로그에 키가 없다. 이때 **Lambda(서울)에서 게이트웨이로 나가는 연결**을 interpret로 확인한다(0007 TODO).
- [ ] **7. Step Functions 생성** (§5). **확인:** 콘솔에서 테스트 실행 1회가 끝까지 간다.
- [ ] **8. API Gateway + 스로틀** (§4.5). api_public에 `STATE_MACHINE_ARN`을 넣는다. **확인:** `POST /public/jobs`가 202와 jobId를 준다.
- [ ] **9. 프론트 빌드·업로드, CloudFront** (§4.6). **확인:** 배포 도메인에서 화면이 열리고 `/api` 요청이 성공한다.
- [ ] **10. 스모크 테스트** (§7).
- [ ] **11. Scheduler** (cleanup 구현 뒤).

## 7. 완료 조건 (스모크 테스트)

1. 배포 도메인에서 도시를 입력하면 jobId가 나오고, 조회가 `QUEUED → RUNNING → SUCCEEDED/PARTIAL`로 바뀐다.
2. 지도에 핀이 나오고, 같은 요청을 다시 보내면 새 작업이 아니라 기존 작업이 돌아온다(requestId).
3. 같은 도시를 두 번째 요청하면 이미 분석한 영상은 **분석을 건너뛴다**(Gemini·게이트웨이 호출 수가 줄어든다. 영상별 토큰은 `VideoAnalysis`에 기록돼 있다).
4. CloudWatch 로그에 키·토큰·좌표·Places 원문이 없다.
5. 첫 실행 결과로 0007의 TODO(verify) 세 가지를 문서에 기록한다: 게이트웨이 연결, 구조화 출력, 키 한도.

## 8. 비용과 보호 장치

- 비용은 **서로 다른 영상 수**에 비례한다(영상별 캐시). 새 도시의 첫 요청만 전체 비용이 든다.
- 막는 장치: 요청당 영상 5개·30분 상한, 목적지 무관 영상 제외, YouTube 검색 하루 90회, 같은 영상 동시 요청은 1회만 분석(선점), API 스로틀, 게이트웨이 `BUDGET_EXCEEDED`는 즉시 중단.
- 빠진 장치: Gemini 하루 예산(C5), 작업당 토큰 상한.

## 9. 결정이 필요한 것 (`docs/decisions/`에 제안으로)

**A. Gemini 요청 제한 (C4).** `RateLimiter`는 프로세스 안에서만 센다.

| 안 | 내용 | 장단점 |
| --- | --- | --- |
| A1 | observe 예약 동시성 1 + Map `MaxConcurrency` 1 (spec §2의 초기값) | 안전하고 구현이 없다. 영상이 한 줄로 가서 1분 목표(결정 0008)를 못 맞춘다. 로컬 실측은 영상당 68~185초 |
| A2 | DynamoDB로 모델별 분당 요청 수를 전역에서 센다(조건부 쓰기) | 병렬을 유지한다. 코드와 테스트가 늘고, 대기 중 Lambda 시간이 든다 |

첫 배포는 A1로 시작하고, 동작을 확인한 뒤 A2로 바꾸는 순서를 제안한다.

**B. 프론트 호스팅.** 현재안은 S3 + CloudFront다. 화면 파일만 정적이고 데이터는 `/api` 뒤 Lambda가 준다. 계정 허용 목록에 호스팅은 이것뿐이고, Google 로그인(M8)은 HTTPS가 필요하다. EC2는 허용 목록에 없고 프로젝트 규칙(상시 서버 금지)과도 충돌한다. 바꾸려면 학교에 EC2 허용을 묻고 결정 기록을 써야 한다.

**C. 값:** `ANALYSIS_VERSION`(C7), API 스로틀(§4.5), 로그 보존 기간(§4.7), Gemini 하루 상한(C5).

## 10. 배포 기록

| 날짜 | 담당 | zip 버전(커밋) | 한 일 | 문제 |
| --- | --- | --- | --- | --- |
| | | | | |

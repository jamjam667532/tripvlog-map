# 인수인계: AWS 백엔드 남은 작업 (2026-11-19)

> 브랜치 `feature/aws-first-deploy`. 전체 안내는 `docs/setup-backend.md`, 명세는 `docs/deploy-runbook.md`.
> 콘솔은 각자 받은 학교 IAM 사용자로 로그인한다. 리전은 **서울(ap-northeast-2)**.

## 1. 지금까지 된 것

| 항목 | 상태 |
| --- | --- |
| S3 `sgu-clicktotrip-data`, `sgu-clicktotrip-config` | 만듦. config 버킷에 `keys.json` 올림 |
| DynamoDB 테이블 6개 | 만듦. GSI 2개 ACTIVE, TTL 2개 ENABLED (CloudShell로 확인) |
| Lambda 8개 | 만듦. 런타임 Python 3.12, 핸들러, 제한 시간, 메모리, 태그, 환경 변수 완료 |
| Lambda 시험 실행 | **통과** (11/19). api-public 404, collect `JobNotFound`. zip·환경 변수·keys.json·DynamoDB 권한 확인됨. 아래 2번은 다시 할 필요 없다 |

## 2. Lambda 시험 실행 (유료 API 호출 없음)

함수를 열고 **테스트** 탭 → 새 이벤트 → JSON 붙여 넣기 → **테스트**.

**`sgu-clicktotrip-api-public`**

```json
{"routeKey": "GET /public/jobs/{jobId}", "pathParameters": {"jobId": "00000000-0000-4000-8000-000000000000"}, "headers": {"x-guest-access-token": "test"}}
```

통과: 결과에 `"statusCode": 404`.

**`sgu-clicktotrip-collect`**

```json
{"jobId": "00000000-0000-4000-8000-000000000000"}
```

통과: 실행이 "실패"로 뜨고 오류 이름이 **`JobNotFound`**. keys.json 읽기와 jobs 테이블 조회가 된 것이다. YouTube는 부르지 않는다.

| 오류 | 볼 곳 |
| --- | --- |
| `Runtime.ImportModuleError` | 런타임이 3.12인지, 핸들러 경로 오타 |
| `NoSuchKey`, `NoSuchBucket`, `AccessDenied`(S3) | keys.json 위치·이름, 버킷 이름 |
| `secret ... is not in the keys file` | keys.json 안의 키 이름 |
| `ResourceNotFoundException`(DynamoDB) | 테이블 이름, 환경 변수 |

## 3. Step Functions

1. 계정 번호(콘솔 오른쪽 위 12자리)를 넣어 정의를 복사한다. 저장소 루트에서:
   ```bash
   sed 's/${account}/계정번호12자리/g' infra/asl/analyze.asl.json | pbcopy
   ```
2. **Step Functions → 상태 머신 생성 → 코드로 작성**에 붙여 넣기. 이름 `sgu-clicktotrip-analyze`, 유형 **Standard**, 실행 역할 **기존 역할** `SafeRole-sgu-clicktotrip`.
3. 만든 상태 머신의 **ARN**을 복사해 `sgu-clicktotrip-api-public`의 **구성 → 환경 변수 → 편집**에서 `STATE_MACHINE_ARN` 값만 바꾼다(지금은 `...:placeholder` 임시 값). 다른 변수는 건드리지 않는다.

## 4. API Gateway

1. **API Gateway → API 생성 → HTTP API**. 이름 `sgu-clicktotrip-api`, 통합은 Lambda `sgu-clicktotrip-api-public`, 페이로드 형식 **2.0**.
2. 경로 2개: `POST /public/jobs`, `GET /public/jobs/{jobId}`. 둘 다 같은 Lambda.
3. 스테이지 `$default`, 자동 배포 켬.
4. **스로틀링** 켜기: 속도 5, 버스트 10. 공개 API를 막는 장치가 이것뿐이다.
5. 확인 (호출 URL로):
   ```bash
   API=https://<api-id>.execute-api.ap-northeast-2.amazonaws.com
   curl -i "$API/public/jobs/00000000-0000-4000-8000-000000000000" -H 'x-guest-access-token: test'
   ```
   통과: **404**. 403·500이면 API Gateway가 Lambda를 부를 권한(리소스 정책)을 본다.

## 5. 전체 시험 1건 (실제 API 호출)

**여기서부터 YouTube·Gemini·Places·게이트웨이 한도를 쓴다. 한 건씩만.** 영상을 하나씩 처리해서 10분 안팎 걸릴 것으로 추정한다.

```bash
curl -s -X POST "$API/public/jobs" -H 'content-type: application/json' \
  -d "{\"requestId\": \"$(uuidgen | tr A-Z a-z)\", \"destination\": \"오사카\"}"
```

응답의 `jobId`, `guestAccessToken`을 적어 둔다(토큰은 이때 한 번만 나온다).

```bash
curl -s "$API/public/jobs/<jobId>" -H 'x-guest-access-token: <토큰>'
```

통과: `status`가 `RUNNING`을 거쳐 `SUCCEEDED` 또는 `PARTIAL`, 결과에 장소가 있다. 진행은 Step Functions 콘솔의 실행 그래프에서 단계별로 보인다.

기록할 것:

- [ ] interpret 단계 성공 여부(Lambda에서 학교 게이트웨이 연결이 처음 확인된다)
- [ ] 영상별 걸린 시간(observe 제한 15분 안인지)
- [ ] 같은 도시를 한 번 더 요청하면 분석을 건너뛰는지(claim이 REUSE)
- [ ] CloudWatch 로그에 키·토큰·좌표가 없는지

## 6. 알아둘 함정 (실제로 겪은 것)

- **2026-11-20 첫 실행:** 영상 6개 중 4개가 interpret에서 실패, 2개도 후보 0~1개였다. 원인은 학교 게이트웨이의
  `bedrock-haiku`가 생각(thinking)을 켠 채 응답해 보이지 않는 토큰이 출력 한도를 먼저 쓴 것. 생각을 끄고
  (`thinking: disabled`) 출력 한도 8,192, 묶음 40개로 고쳤다. 분석 버전을 `v3-seg190`으로 올렸다.
- **상태 머신을 CLI로 만들면 학교 태그가 자동으로 안 붙는다.** `group=sgu-clicktotrip`, `username=<IAM 사용자>`를
  직접 붙인다(`aws stepfunctions tag-resource`).
- **SafeRole에 `states:StartExecution`이 처음엔 없었다.** 2026-11-20 담당자 요청으로 추가됨.
- **콘솔에서 먼저 만든 함수는 스크립트가 zip을 올리지 않는다.** 8개 모두 `CodeSize`가 약 10MB인지 확인한다:
  `aws lambda list-functions --query "Functions[?starts_with(FunctionName,'sgu-clicktotrip-')].[FunctionName,CodeSize]" --output table`

- **새로 만든 리소스는 10~20초 뒤에 학교 태그가 자동으로 붙는다.** 그 전에 조회·수정하면 `explicit deny`로 거부된다. 잠시 기다렸다 다시 하면 된다.
- **콘솔에서 Lambda를 새로 만들면 기본 런타임이 Python 3.15다.** 우리 zip은 3.12 전용이라 반드시 3.12로 고른다.
- **CloudShell 파일 업로드가 `Too many requests`로 막히면** 1~2분 기다렸다 다시 한다.
- 키 값과 `keys.json` 내용은 채팅·스크린샷·로그에 올리지 않는다. 막히면 단계 번호, 함수 이름, 오류 문구만 공유한다.

## 7. 이번 범위가 아닌 것

- 프론트 배포(S3 + CloudFront): 백엔드 전체 시험이 통과한 뒤.
- 영상 병렬 처리(Gemini 분당 제한 전역화)와 Gemini 하루 상한: 결정이 필요하다(`docs/deploy-runbook.md` §9).

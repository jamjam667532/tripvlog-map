# 인수인계: AWS 배포 (2026-11-19 시작, 2026-11-22 1단계 배포 완료)

> 브랜치 `feature/youtube-taste`(최신, 2026-11-22 이후 배포 수정 포함. `feature/aws-first-deploy`는 그 이전 상태). 전체 안내는 `docs/setup-backend.md`, 명세는 `docs/deploy-runbook.md`.
> 콘솔은 각자 받은 학교 IAM 사용자로 로그인한다. 리전은 **서울(ap-northeast-2)**.

## 1. 지금까지 된 것

| 항목 | 상태 |
| --- | --- |
| S3 `sgu-clicktotrip-data`, `sgu-clicktotrip-config` | 만듦. config 버킷에 `keys.json` 올림 |
| DynamoDB 테이블 6개 | 만듦. GSI 2개 ACTIVE, TTL 2개 ENABLED (CloudShell로 확인) |
| Lambda 8개 | 만듦. 런타임 Python 3.12, 핸들러, 제한 시간, 메모리, 태그, 환경 변수 완료 |
| Lambda 시험 실행 | **통과** (11/19). api-public 404, collect `JobNotFound`. zip·환경 변수·keys.json·DynamoDB 권한 확인됨. 아래 2번은 다시 할 필요 없다 |
| **프론트 배포** | **완료** (2026-11-22). S3 `sgu-clicktotrip-web` + CloudFront `https://d1iehbeyllkxs5.cloudfront.net`(OAC, WAF 끔, 태그 2개). 화면이 API Gateway를 직접 부르고 CORS로 허용 |
| **화면에서 전체 확인** | **성공** (2026-11-22). 도쿄: 영상 5개 성공, 장소 40곳, 1위는 채널 2개에서 확인 |
| **첫 전체 실행** | **성공** (2026-11-22). 오사카 영상 5/5, 약 3분 30초, 확정 장소 35곳(2곳은 채널 2개에서 확인). API Gateway → Lambda → Step Functions → YouTube·Gemini·게이트웨이·Places → 결과 JSON |

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

- **GSI 키 이름은 대소문자까지 정확히.** 2026-11-22에 places의 `videoId-index` 정렬 키가 `evidencekey`(k 소문자)로 만들어져 근거가 색인되지 않았고, 매칭은 44곳 확정인데 결과는 0곳이었다. GSI는 수정이 안 돼서 지우고 `evidenceKey`로 다시 만들었다(색인 약 10분). 만든 뒤 반드시 확인:
  `aws dynamodb describe-table --table-name sgu-clicktotrip-places --query 'Table.GlobalSecondaryIndexes[].KeySchema'`

- **2026-11-20 첫 실행:** 영상 6개 중 4개가 interpret에서 실패, 2개도 후보 0~1개였다. 원인은 학교 게이트웨이의
  `bedrock-haiku`가 생각(thinking)을 켠 채 응답해 보이지 않는 토큰이 출력 한도를 먼저 쓴 것. 생각을 끄고
  (`thinking: disabled`) 출력 한도 8,192, 묶음 40개로 고쳤다. 분석 버전을 `v3-seg190`, 이어서 `v4-seg190`으로 올렸다.
- **CloudShell 파일 업로드는 같은 이름의 파일을 덮어쓰지 않을 수 있다.** 2026-11-22에 예전 `backend.zip`이 그대로 남아 예전 코드가 배포됐다. 올리기 전에 `rm backend.zip`, 올린 뒤 `ls -l`로 크기를 확인한다.
- **상태 머신을 CLI로 만들면 학교 태그가 자동으로 안 붙는다.** `group=sgu-clicktotrip`, `username=<IAM 사용자>`를
  직접 붙인다(`aws stepfunctions tag-resource`).
- **SafeRole에 `states:StartExecution`이 처음엔 없었다.** 2026-11-20 담당자 요청으로 추가됨.
- **콘솔에서 먼저 만든 함수는 스크립트가 zip을 올리지 않는다.** 8개 모두 `CodeSize`가 약 10MB인지 확인한다:
  `aws lambda list-functions --query "Functions[?starts_with(FunctionName,'sgu-clicktotrip-')].[FunctionName,CodeSize]" --output table`

- **새로 만든 리소스는 10~20초 뒤에 학교 태그가 자동으로 붙는다.** 그 전에 조회·수정하면 `explicit deny`로 거부된다. 잠시 기다렸다 다시 하면 된다.
- **콘솔에서 Lambda를 새로 만들면 기본 런타임이 Python 3.15다.** 우리 zip은 3.12 전용이라 반드시 3.12로 고른다.
- **CloudShell 파일 업로드가 `Too many requests`로 막히면** 1~2분 기다렸다 다시 한다.
- 키 값과 `keys.json` 내용은 채팅·스크린샷·로그에 올리지 않는다. 막히면 단계 번호, 함수 이름, 오류 문구만 공유한다.

## 7. 지금 배포된 주소와 이름

| 항목 | 값 |
| --- | --- |
| 화면 | `https://d1iehbeyllkxs5.cloudfront.net` |
| API | `https://dp4nohrcak.execute-api.ap-northeast-2.amazonaws.com` (스로틀 5/10, CORS는 화면 주소만 허용) |
| 상태 머신 | `sgu-clicktotrip-analyze` (태그 `group`, `username` 직접 붙임) |
| 분석 버전 | `v4-seg190` |

**화면을 다시 올리는 법:** 저장소 루트에서
```bash
cd frontend && VITE_API_BASE=https://dp4nohrcak.execute-api.ap-northeast-2.amazonaws.com npm run build
```
`frontend/.env.local`에 지도 키(`VITE_GOOGLE_MAPS_API_KEY`)가 있어야 한다. 만들어진 `frontend/dist` **안의 내용**을 S3 `sgu-clicktotrip-web` 최상위에 덮어 올린다. 파일 이름에 해시가 붙어 바로 반영된다(`index.html`은 CloudFront 캐시 때문에 몇 분 걸릴 수 있다. 급하면 CloudFront에서 `/index.html` 무효화).

## 8. 남은 일

| 일 | 이유 |
| --- | --- |
| **지도 키 분리** | 지금 지도 키 = YouTube·Places 서버 키(같은 키 `y4s2prjct`). 화면 코드에 공개된 키로 서버 API까지 부를 수 있다. 지도 전용 키(웹사이트 제한 + Maps JavaScript API만)를 새로 만들고 프론트를 다시 빌드한다. **기존 키에 웹사이트 제한을 걸면 Lambda의 YouTube·Places 호출이 막힌다** |
| 지역 이름 | 결과의 지역 묶음이 "지역 1~16". 이름을 붙이는 규칙이 없다 |
| 목적지 밖 장소 | 오사카 결과에 교토 장소가 섞였다. 도시 반경으로 거를지 결정 필요 |
| 영상 병렬 처리 | Map 동시성 1이라 영상이 한 줄로 간다(약 3분 30초). 1분 목표에는 Gemini 분당 제한을 Lambda 전체에서 세는 장치가 필요(runbook §9-A) |
| 로그인·취향 기능 | `docs/handoff-youtube-taste.md` |

## 9. 이번 범위가 아닌 것

- 프론트 배포(S3 + CloudFront): 백엔드 전체 시험이 통과한 뒤.
- 영상 병렬 처리(Gemini 분당 제한 전역화)와 Gemini 하루 상한: 결정이 필요하다(`docs/deploy-runbook.md` §9).

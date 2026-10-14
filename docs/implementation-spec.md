# 구현 명세 (Implementation Spec)

> 대상 독자: 이 저장소에서 코드를 작성하는 Claude Code(Opus)와 팀원.
> 기획 배경과 근거는 `docs/기획서.md`, 프로젝트 규칙은 루트 `CLAUDE.md`를 따른다.
> 기준일: 2026-10-14. 모델 ID·한도·가격은 바뀔 수 있으므로 `TODO(verify)` 표시가 있는 값은 콘솔에서 확인한 뒤 설정 파일에 넣는다.

---

## 1. 목표와 범위

### 1.1 사용자가 받는 결과

목적지(예: "오사카")와 선택 입력(선호 스타일, 동행)을 넣으면:

- Google 지도 위 장소 핀 (식당·카페·관광지), 지역별 묶어 보기
- 장소별 채널 근거: "분석한 5개 채널 중 4개에서 방문 확인 · 명시적 긍정 3 · 대기 불만 1"
- 장소별 방문 시간대 근거: 종류(장면 관찰 / 방문 시각 언급 / 대기 경험 / 제작자 추천)를 구분해 표시
- 근거 문장과 영상 재생 위치 링크 (`https://youtu.be/{id}?t={startSec}`)
- 미확정 장소는 후보로 따로 표시

### 1.2 범위 밖 (구현 금지)

일자별 일정, 방문 순서, 경로, 기간·숙소 입력, 실시간 혼잡도, 영상 다운로드, 국내 여행지, Routes API.

### 1.3 단계

| 단계 | 내용 |
| --- | --- |
| 1단계 (첫 검증) | 비로그인 경로만. 목적지·스타일·동행 입력, 영상 5개 순차 분석, 지도 출력, 규칙 vs Bedrock 비교 실험 |
| 2단계 | Cognito Google 로그인, `/me/preferences`, 유튜브 1회 연결, 개인 순위 재계산 |
| 조건부 | Gemini 불허 시 업로드 모드(Nova Lite + Transcribe). 지시가 있을 때만 구현 |

---

## 2. 아키텍처

```
Browser (React SPA)
  ├─ CloudFront ─┬─ S3 (정적 파일, OAC, 비공개)
  │              └─ /api/* → API Gateway HTTP API (캐시 끔)
  │                   ├─ /public/*      → Lambda api_public   (인증 없음, 요청 제한)
  │                   ├─ /jobs, /jobs/* → Lambda api_jobs     (Cognito JWT)
  │                   └─ /me/*          → Lambda api_me       (Cognito JWT)
  └─ Maps JavaScript API (브라우저 지도 키, 도메인 제한)

api_public / api_jobs ── StartExecution(name=jobId) ──▶ Step Functions "analyze"
  1. collect     (YouTube Data API, 규칙 필터)
  2. Map(videoRefs, MaxConcurrency=1 초기값)
       ├─ claim      (VideoAnalysis 조건부 선점 / 재사용 / 대기)
       ├─ observe    (Gemini, 예약 동시성으로 전역 제한)
       ├─ interpret  (Bedrock Converse, Pydantic 검증)
       └─ match      (Places Text Search + 규칙 매칭)
     영상별 Catch → 실패 기록, 다른 영상은 계속
  3. aggregate   (채널별 집계, 시간대 근거, 순위, 결과 JSON → S3)

EventBridge Scheduler (매일) → Lambda cleanup (만료 캐시·연결 데이터 명시적 삭제)
```

### 2.1 리전·모델 설정

`infra/config.py` (환경별 값):

```python
REGION = "us-east-1"                      # TODO(verify): 학교 계정에서 허용된 US 리전
BEDROCK_INTERPRETER_MODEL_ID = "..."      # TODO(verify): Claude Haiku 4.5 모델 ID 또는 추론 프로파일(us. 접두사)
BEDROCK_COMPARE_MODEL_ID = "..."          # TODO(verify): GPT 5.6 Luna 모델 ID
BEDROCK_STYLE_MODEL_ID = "..."            # TODO(verify): Amazon Nova Micro 모델 ID
GEMINI_MODEL = "..."                      # TODO(verify): 무료 티어에서 YouTube URL 입력을 지원하는 Flash 계열
ANALYSIS_VERSION = "v1-haiku45"           # 모델·프롬프트·스키마가 바뀌면 올린다
MAX_VIDEOS_PER_JOB = 5
OBSERVE_RESERVED_CONCURRENCY = 1          # Gemini 전역 동시 호출 수. 첫 검증 후 조정
COORD_TTL_DAYS = 25
YOUTUBE_CACHE_TTL_DAYS = 25               # 30일 이내 갱신·삭제 운영안
```

Bedrock 호출은 `bedrock-runtime`의 Converse API로 통일하고 모델 ID만 바꿔 쓴다. 모델이 Converse를 지원하지 않으면 어댑터에서 InvokeModel로 분기한다.

---

## 3. API 계약

모든 응답은 JSON. 오류는 `{"error": {"code": "STRING", "message": "..."}}`.

### 3.1 `POST /public/jobs` (인증 없음)

요청:
```json
{ "requestId": "uuid-v4", "destination": "오사카", "styles": ["맛집"], "companion": "커플" }
```
- `styles`: `맛집 | 카페·포토스팟 | 관광·역사 | 쇼핑 | 가성비` 중 0~3개
- `companion`: `혼자 | 커플 | 친구 | 가족 | null`
- 요청 제한: IP·전역 일일 예산(설정값). 초과 시 429.

응답 `202`:
```json
{ "jobId": "uuid-v4", "guestAccessToken": "base64url-32bytes", "status": "QUEUED" }
```
- `guestAccessToken`은 이 응답에서 한 번만 반환. DB에는 `sha256(token)`만 `guestAccessHash`로 저장.
- 같은 `requestId`가 다시 오면 새 작업을 만들지 않고 기존 jobId를 반환(토큰은 재발급하지 않음 → 409 `DUPLICATE_REQUEST`와 jobId).

### 3.2 `GET /public/jobs/{jobId}`

헤더 `X-Guest-Access-Token: <token>` 필수. 해시 불일치·누락 시 404(존재 여부를 숨긴다).

응답 `200`:
```json
{
  "jobId": "...",
  "status": "QUEUED | RUNNING | SUCCEEDED | PARTIAL | FAILED",
  "progress": { "total": 5, "analyzed": 3, "failed": 0 },
  "videos": [ { "videoId": "abc", "state": "PENDING | ANALYZING | DONE | FAILED | SKIPPED" } ],
  "result": null
}
```
종료 상태(SUCCEEDED, PARTIAL, FAILED)면 `result`에 결과 JSON(§6.4)을 담는다. 결과는 S3에서 읽어 API가 반환하며 S3 URL을 직접 노출하지 않는다.

### 3.3 로그인 경로 (2단계)

| 메서드·경로 | 설명 |
| --- | --- |
| `POST /jobs` | 3.1과 같은 본문. userId는 JWT `sub`. 저장된 선호와 요청 선호를 병합 |
| `GET /jobs/{jobId}` | Jobs.userId == sub 일 때만. 아니면 404 |
| `POST /jobs/{jobId}/rerank` | 본문 `{ "styles": [...], "companion": "..." }`. 규칙으로 순위만 재계산. 모델 호출 금지 |
| `GET /me/preferences` | Users의 선호·연결 상태 |
| `PATCH /me/preferences` | 선호·참고 채널 수정 |
| `POST /me/youtube/import` | 헤더 `X-Google-Access-Token`. 구독·좋아요를 1회 조회해 후보 반환. 토큰 저장·로깅 금지 |
| `POST /me/youtube/confirm` | 사용자가 확인한 참고 채널·스타일을 Users에 저장 |
| `DELETE /me/youtube/connection` | 연결 데이터 속성 REMOVE |

---

## 4. 데이터 모델 (DynamoDB, 온디맨드)

| 테이블 | PK | SK | GSI | TTL 속성 |
| --- | --- | --- | --- | --- |
| Users | `userId` (Cognito sub) | - | - | - (연결 데이터는 cleanup이 속성 REMOVE) |
| Jobs | `jobId` | - | `requestId-index` (PK requestId) | - |
| YoutubeCache | `pk` (`SEARCH#{hash}` / `VIDEO#{videoId}`) | `sk` (`RESULT` / `META`) | - | `expiresAt` (보조) |
| VideoAnalysis | `videoId` | `analysisVersion` | - | - |
| Places | `placeId` | `sk` (`PLACE` / `EVID#{channelId}#{videoId}#{analysisVersion}#{startSec}`) | `videoId-index` (PK `videoId`, SK `evidenceKey`) | - |
| CoordCache | `placeId` | - | - | `expiresAt` (보조) |

규칙:
- YoutubeCache 값 필드(결정 0002-3): `SEARCH`/`RESULT`는 `videoIds`, `VIDEO`/`META`는 `channelId, title, description, durationSec, privacyStatus, publishedAt`. 조회수·좋아요 수·구독자 수는 저장하지 않는다.
- `SEARCH#{hash}`의 hash는 목적지·검색어·정렬·페이지·언어·기간 필터 전체를 정규화해 만든다.
- Places의 `PLACE` 아이템에는 `videoId`가 없으므로 GSI에 들어가지 않는다(희소 인덱스).
- `evidenceKey` = `{placeId}#{analysisVersion}#{startSec}`.
- 모든 아이템은 Pydantic 모델로 쓰고 읽는다(`backend/shared/schemas/items.py`).

### 4.1 Jobs 아이템

```json
{
  "jobId": "uuid",
  "requestId": "uuid",
  "userId": "cognito-sub | null",
  "guestAccessHash": "sha256-hex | null",
  "status": "QUEUED",
  "request": { "destination": "오사카", "styles": ["맛집"], "companion": "커플" },
  "videoRefs": [ { "videoId": "abc", "channelId": "ch1", "analysisVersion": "v1-haiku45", "state": "PENDING | ANALYZING | DONE | FAILED | SKIPPED", "error": null } ],
  "progress": { "total": 5, "analyzed": 4, "failed": 1 },
  "executionArn": "...",
  "resultS3Key": "results/{jobId}/result.json",
  "metrics": { "elapsedSec": 0, "geminiTokens": 0, "bedrockInputTokens": 0, "bedrockOutputTokens": 0, "placesCalls": 0, "youtubeUnits": 0 },
  "createdAt": "ISO8601", "updatedAt": "ISO8601"
}
```

### 4.2 VideoAnalysis 아이템

```json
{
  "videoId": "abc", "analysisVersion": "v1-haiku45",
  "status": "ANALYZING | DONE | FAILED",
  "lockOwner": "jobId", "leaseUntil": 1790000000,
  "channelId": "ch1", "styleTag": "맛집 | 복합 | 분류불가",
  "observationS3Key": "analysis/abc/v1-haiku45/observation.json",
  "interpretationS3Key": "analysis/abc/v1-haiku45/interpretation.json",
  "usage": { "geminiTokens": 0, "bedrockInputTokens": 0, "bedrockOutputTokens": 0 },
  "analyzedAt": "ISO8601", "lastCheckedAt": "ISO8601"
}
```

선점(claim) 규칙 — 조건부 UpdateItem:
- 아이템 없음 → `ANALYZING`, `lockOwner=jobId`, `leaseUntil=now+15분` 으로 생성 후 분석 진행
- `DONE` → 재사용 (분석 생략)
- `ANALYZING` 이고 `leaseUntil > now` → 대기(Step Functions Wait 30초 후 재확인, 최대 N회)
- `ANALYZING` 이고 `leaseUntil <= now` 또는 `FAILED` → 선점 회수 후 재분석

### 4.3 Places 근거 아이템

```json
{
  "placeId": "ChIJ...", "sk": "EVID#ch1#abc#v1-haiku45#750",
  "videoId": "abc", "channelId": "ch1", "analysisVersion": "v1-haiku45",
  "evidenceKey": "ChIJ...#v1-haiku45#750",
  "visitStatus": "VISITED | MENTIONED | UNCLEAR",
  "matchStatus": "CONFIRMED | UNCONFIRMED",
  "videoTimeRange": { "startSec": 750, "endSec": 905 },
  "clueTypes": ["SPEECH", "SCREEN_TEXT", "SCENE"],
  "ratings": { "overall": "POSITIVE | NEGATIVE | MIXED | NONE | UNDETERMINED", "taste": "...", "price": "...", "wait": "...", "service": "..." },
  "evidenceText": "원문 발화 또는 자막 (최대 200자)",
  "visitTimeEvidence": [
    { "kind": "SCENE | STATED_TIME | WAIT_EXPERIENCE | CREATOR_TIP", "situation": "OPENING | MORNING | LUNCH_PEAK | AFTERNOON | EVENING | NIGHT | SUNSET | DAY | OTHER", "localClockTime": "09:00 | null", "evidenceText": "..." }
  ]
}
```

`PLACE` 아이템: `{placeId, sk:"PLACE", destination, extractedName, aliases[], categoryFromVideo}` — 이름은 영상에서 관찰한 표기만. Google 응답 필드 저장 금지.

### 4.4 Users (2단계)

```json
{
  "userId": "cognito-sub",
  "preferences": { "styles": ["맛집"], "companion": "커플", "referenceChannelIds": ["ch1"] },
  "youtube": {
    "linked": true, "syncedAt": "ISO8601", "resyncDueAt": "ISO8601(+25일)",
    "travelChannelIds": ["ch1"], "likedTravelVideoIds": ["abc"], "styleProfileCandidate": { "맛집": 0.6 }
  }
}
```
사용자 직접 선호(`preferences`)와 API 유래 데이터(`youtube`)를 분리한다. 연결 해제·만료 시 `youtube`만 REMOVE.

---

## 5. 파이프라인 단계별 명세

### 5.1 collect

입력 `{jobId}` → 출력 `{jobId, videoRefs:[{videoId, channelId, analysisVersion}]}`

1. 검색어 3개 생성: `"{dest} 브이로그"`, `"{dest} 맛집"`, `"{dest} 여행"`. 정렬은 relevance와 date 혼합. 각 1페이지.
2. YoutubeCache(SEARCH) 유효하면 재사용, 아니면 `search.list` 호출 후 저장. 일일 검색 횟수 카운터를 두고 상한 초과 시 캐시만 사용.
3. `videos.list`로 메타데이터(길이, 공개 여부, 채널) 조회 → YoutubeCache(VIDEO) 저장.
4. 규칙 필터: 같은 영상 제거, 공개만, 길이 ≥ 3분, 최근 2년, 채널당 1개, 재업로드 의심은 표시만(제외하지 않음). 장소 겹침으로 거르지 않는다.
5. 스타일 태그(Nova Micro, 제목+설명란): 사용자 선호 스타일 영상을 우선하되 채널 수 확보가 우선. 정책 확인 전에는 `STYLE_TAGGING_ENABLED=false`로 두고 규칙 키워드 태깅만 사용.
6. 최대 5개 선택, Jobs.videoRefs 기록. 남은 후보 중 다른 채널 영상을 예비로 최대 `SPARE_VIDEOS_PER_JOB`개 Jobs.spareVideos에 기록(결정 0002-5).

### 5.2 observe (Gemini)

- google-genai SDK로 YouTube URL을 파일 데이터로 전달한다(정확한 호출 형식은 SDK 문서 확인, `TODO(verify)`).
- 출력은 JSON 모드 + `ObservationResult` 스키마로 검증. 실패 시 1회 재요청, 그래도 실패면 영상 FAILED.
- 결과는 S3 `analysis/{videoId}/{version}/observation.json`. Step Functions에는 S3 키만 반환.
- 타임아웃: SDK < Lambda(설정 900초 이하) < Step Functions Task. 첫 실행에서 실제 소요 시간을 metrics에 기록.

`ObservationResult` (Pydantic):

```python
class Clue(BaseModel):
    start_sec: int
    end_sec: int
    clue_type: Literal["SPEECH", "SCREEN_TEXT", "SCENE"]
    heard_name: str | None          # 들린 장소명 원문
    seen_text: str | None           # 간판·자막·메뉴판에서 읽은 글자
    utterance: str | None           # 장소 주변 발화·편집 자막 원문 (평가·시간 근거)
    scene: str | None               # 방문을 보여주는 장면 한 줄
    scene_daypart: Literal["DAY", "NIGHT", "UNKNOWN"]
    uncertainty: list[Literal["INAUDIBLE", "TEXT_UNCLEAR", "TARGET_AMBIGUOUS"]]

class ObservationResult(BaseModel):
    video_id: str
    clues: list[Clue]
```

Gemini 프롬프트 요지 (`backend/shared/prompts/observe.md`):
- 너는 관찰자다. 장소를 결론 내리거나 평가를 요약하지 마라.
- 들린 말, 보인 글자, 장면만 시간 구간과 함께 기록하라.
- 들리지 않거나 읽히지 않으면 null과 uncertainty를 쓰고 추측하지 마라.
- 장소와 관련된 맛·가격·대기·서비스·시간 언급은 원문 그대로 utterance에 넣어라.
- 출력은 지정된 JSON 스키마만.

### 5.3 interpret (Bedrock)

입력: observation S3 키 → 출력: interpretation S3 키.

`InterpretationResult`:

```python
class PlaceCandidate(BaseModel):
    candidate_id: str
    names: list[str]                    # 원문 표기 유지 (예: ["이치란", "一蘭"])
    branch_hint: str | None             # "도톤보리" 등. 근거 없으면 None
    search_queries: list[str]           # 최대 3개. 근거 없는 상호·지점 생성 금지
    category: Literal["RESTAURANT", "CAFE", "ATTRACTION", "OTHER"]
    visit_status: Literal["VISITED", "MENTIONED", "UNCLEAR"]
    clue_refs: list[int]                # Observation.clues 인덱스. 근거 연결 필수
    ratings: Ratings                    # 항목별. 근거 없으면 NONE
    time_evidence: list[TimeEvidence]   # kind/situation/localClockTime/evidenceText

class InterpretationResult(BaseModel):
    video_id: str
    analysis_version: str
    candidates: list[PlaceCandidate]
```

검증 규칙(코드):
- `clue_refs`가 비어 있거나 범위 밖이면 그 후보는 버린다.
- `time_evidence.kind == "SCENE"`이면 situation은 `DAY | NIGHT`만 허용하고, 다른 값이면 그 시간 근거 항목만 버린다. `CREATOR_TIP`로 바꾸지 않는다. (결정 0002-1)
- `localClockTime`은 `STATED_TIME`일 때만 허용. 다른 kind면 null로 강제.
- ratings 값은 Enum 외 값이면 `UNDETERMINED`.
- 형식 검증에 실패하면 그 영상의 Bedrock만 1회 재요청한다. 그래도 실패하면 영상 FAILED 후 예비 영상으로 대체한다(이미 분석된 예비 영상 우선, 없으면 가장 짧은 영상, 작업당 `MAX_REPLACEMENTS_PER_JOB`개까지). (결정 0002-5)

Haiku 프롬프트 요지 (`backend/shared/prompts/interpret.md`): 관찰 근거만 사용, 서로 다른 지점 합치지 않기, 단순 언급과 방문 구분, 평가 대상이 모호하면 UNCLEAR, 장면만으로 시간 추천 만들지 않기, 재생 위치를 방문 시각으로 쓰지 않기.

### 5.4 match (Places + 규칙)

- 후보별 `search_queries`를 순서대로 Text Search (도시 위치 편향, 언어 ko). 호출 예산: 후보당 최대 2회.
- 요청 필드는 장소 ID·이름·좌표·주소 요약 등 매칭에 필요한 최소 필드만(FieldMask).
- 매칭 규칙(`rules/matching.py`, 순수 함수):
  1. 이름 유사도(정규화 후 문자열 유사도 + 별칭) ≥ 임계값
  2. `branch_hint`가 있으면 결과 이름·주소에 포함돼야 함
  3. 남은 후보가 정확히 1개면 CONFIRMED, 0개면 버림, 2개 이상이면 UNCONFIRMED(후보 목록 보존)
  4. 거리 조건은 영상에 위치 단서가 있을 때만
- CONFIRMED면 Places에 근거 아이템 저장, 좌표는 CoordCache(25일).
- Places 응답 원문은 메모리에서만 사용. 로그·S3 저장 금지.

### 5.5 aggregate

- 입력 범위: 이 작업의 `videoRefs` 중 `state=DONE`인 영상의 근거만(`videoId-index` Query 후 analysisVersion 필터).
- 장소별:
  - `channelsVisited` = VISITED 근거가 있는 서로 다른 채널 수 (채널당 1표)
  - `denominator` = 분석 성공 채널 수 (실패 채널 제외)
  - 평가: 항목별로 채널 단위 집계. 같은 채널 내 상충은 MIXED. NONE은 긍정으로 세지 않음
  - 시간대 근거: kind·situation별 채널 수, 상충 그대로 나열. "추천" 표현은 CREATOR_TIP이 있거나 같은 방향 WAIT_EXPERIENCE가 2채널 이상일 때만
- 순위(`rules/ranking.py`): 기본 점수 = 방문 채널 수 + 명시적 긍정 가중. 선호 스타일 일치·참고 채널 방문에 가중치. 조회수 등 API 지표 사용 금지.
- 지역 묶음: 좌표 기준 간단한 그리드 또는 k-means(numpy). 일자·순서 개념 없음.
- 결과 JSON을 `results/{jobId}/result.json`에 저장, Jobs 갱신. 실패 영상이 있으면 PARTIAL. `results/`에는 S3 수명 주기 25일(결정 0002-4).

### 5.6 cleanup (매일)

- CoordCache, YoutubeCache: `expiresAt < now` Scan(페이지 처리) → BatchWriteItem 삭제, 미처리 항목 재시도.
- Users: `youtube.resyncDueAt + 5일 < now` → `youtube` 속성 REMOVE.
- VideoAnalysis: 마지막 확인 후 25일 지난 영상은 `videos.list`로 공개 상태 확인, 비공개·삭제면 분석·근거 삭제.
- 실패 시 CloudWatch 경보.

---

## 6. 프론트엔드

### 6.1 화면

1. 입력: 목적지, 스타일(칩 다중 선택), 동행(선택), 분석 시작
2. 진행: 영상별 상태(대기·분석 중·완료·실패), 폴링 3초, 종료 상태에서 중단, 최대 10분 후 안내
3. 결과: 왼쪽 장소 목록(순위·지역 필터·미확정 토글), 오른쪽 Google 지도. 장소 카드에 채널 근거, 시간대 근거(종류 배지), 영상 링크
4. (2단계) 로그인, 내 선호, 유튜브 연결·확인·해제

### 6.2 상태 관리

- 비로그인 `jobId`, `guestAccessToken`은 sessionStorage에 저장(실패해도 동작하도록 try/catch).
- TanStack Query로 `GET /public/jobs/{id}` 폴링.

### 6.3 표현 규칙

- "추천"은 aggregate가 recommend 플래그를 준 경우만. 그 외는 "영상 속 경험".
- 재생 위치는 "영상 12:30 지점"처럼 표기하고 방문 시각처럼 보이지 않게.
- 표본 수를 항상 표시: "분석 성공 4개 채널 중".

### 6.4 결과 JSON (API가 반환)

```json
{
  "jobId": "...", "destination": "오사카", "analyzedChannels": 4, "failedVideos": 1,
  "places": [
    {
      "placeId": "ChIJ...", "name": "이치란 · 도톤보리", "category": "RESTAURANT",
      "lat": 34.6687, "lng": 135.5013, "areaGroup": "도톤보리",
      "rank": 1, "matchStatus": "CONFIRMED",
      "channels": { "visited": 4, "denominator": 4 },
      "ratings": { "taste": { "positive": 3, "negative": 0, "mixed": 1 }, "wait": { "positive": 1, "negative": 2, "mixed": 0 } },
      "timeEvidence": [ { "kind": "WAIT_EXPERIENCE", "situation": "OPENING", "channels": 2, "recommend": true } ],
      "evidence": [ { "channelId": "ch1", "videoId": "abc", "startSec": 750, "text": "..." } ]
    }
  ],
  "unconfirmed": [ { "names": ["..."], "reason": "MULTIPLE_BRANCHES" } ]
}
```
좌표는 응답에만 포함하고 프론트에서 저장하지 않는다. `name`은 Google 이름이 아니라 영상 기반 표기(영상 이름 + `branch_hint`, 예: "이치란 · 도톤보리")다. 화면의 지점명은 프론트가 `placeId`로 Google에서 받아 표시만 하고, 실패하면 `name`을 보여준다(결정 0002-4).

---

## 7. 보안·정책 체크리스트

- [ ] `/public/*`에 요청 제한·전역 일일 예산, `/jobs`, `/me/*`에 JWT Authorizer
- [ ] guestAccessToken 원문 미저장, 비교는 상수 시간 비교
- [ ] 로그 필터: Authorization, X-Guest-Access-Token, X-Google-Access-Token 마스킹
- [ ] CloudFront `/api/*` 캐시 비활성, 필요한 헤더만 전달
- [ ] S3 정적 버킷 OAC, 결과 버킷은 Lambda 역할만 접근
- [ ] 서버 키는 Parameter Store, 지도 키는 도메인·API 제한
- [ ] Places 원문·좌표 로그 금지, Google 응답 필드 영구 저장 금지
- [ ] 조회수·좋아요 수 등 API 지표를 점수에 사용하지 않음

---

## 8. 테스트

| 종류 | 대상 | 도구 |
| --- | --- | --- |
| 단위 | rules/ (matching, aggregation, time_evidence, ranking), schemas 검증 | pytest |
| 계약 | Gemini·Bedrock 출력 fixture → Pydantic 통과/실패 케이스 | pytest |
| 통합 | DynamoDB Local + moto(S3, SSM) 로 collect→aggregate 흐름, 외부 API는 fake client | pytest |
| 프론트 | 결과 렌더링, 폴링 종료, 표현 규칙 | Vitest |
| 스모크 (배포 후) | `/public/jobs` 접수 → 캐시된 fixture 목적지로 조회 | GitHub Actions |

필수 테스트 케이스:
- 같은 채널이 같은 장소를 3번 언급 → 1표
- MENTIONED만 있는 채널 → 방문으로 세지 않음
- 영상 1개 FAILED → 분모에서 제외, 상태 PARTIAL
- SCENE NIGHT만 있음 → recommend=false
- STATED_TIME 외 kind에 localClockTime이 오면 null로 강제
- 체인 지점 2개 남음 → UNCONFIRMED
- 같은 영상 동시 요청 → Gemini 1회만 호출
- guestAccessToken 불일치 → 404
- `rerank` 호출 시 Bedrock·Gemini 클라이언트 미호출

---

## 9. 실험 (`experiments/`)

- `labels/`: 사람이 작성한 정답(장소, 지점, 방문/언급, 평가, 시간 근거 kind, 재생 위치). Google 응답을 정답으로 쓰지 않음. 조정용(dev)과 평가용(test) 분리.
- `run_compare.py`: 같은 observation으로 (a) 키워드 규칙 해석, (b) Haiku, (c) Luna 실행 → 지점 매칭률, 방문/언급 F1, 평가 대상 연결 정확도, 시간 근거 분류 정확도, 지연·토큰 비용 표 출력.
- 결과는 `experiments/results/{date}.md`로 저장. 5개 영상 결과는 가능성 확인용으로만 표기.

---

## 10. CI/CD

- `ci.yml` (PR): ruff, mypy, eslint, tsc, pytest, vitest, Lambda 이미지 빌드, Trivy 스캔, `cdk synth`. AWS 자격증명이 필요한 `cdk diff`는 내부 브랜치에서만.
- `deploy.yml` (main): OIDC로 AWS 인증 → 이미지 SHA 태그로 ECR 푸시 → `cdk deploy` → 프론트 빌드·S3 업로드·CloudFront 무효화 → 스모크 테스트(fixture, 유료 호출 없음).
- 학교 계정에서 OIDC·CDK bootstrap이 막히면: CI는 검사만, 배포는 허용된 로컬 자격증명으로. IAM 자체가 막히면 사람에게 알린다.

---

## 11. 구현 순서 (마일스톤)

각 마일스톤은 완료 조건을 만족해야 다음으로 넘어간다.

| # | 내용 | 완료 조건 |
| --- | --- | --- |
| M0 | 저장소 골격, Makefile, docker compose, CI(ci.yml), pre-commit(ruff, gitleaks) | `make lint`, `make test` 통과 (빈 테스트 포함) |
| M1 | `shared/schemas` 전체 Pydantic 모델 + fixture 기반 계약 테스트 | 정상·비정상 fixture 테스트 통과 |
| M2 | `shared/rules` (matching, aggregation, time_evidence, ranking) 순수 함수 + 필수 테스트 케이스 | §8 필수 케이스 중 규칙 관련 전부 통과 |
| M3 | `shared/clients` (youtube, gemini, bedrock, places) + fake 구현 | fake로 통합 테스트 가능 |
| M4 | Lambda 핸들러 collect·claim·observe·interpret·match·aggregate + DynamoDB Local 통합 테스트 | fixture 영상 2개로 end-to-end 결과 JSON 생성 |
| M5 | CDK 스택 (DynamoDB, S3, Lambda 이미지, Step Functions, HTTP API `/public/*`, CloudFront, Scheduler) | `cdk synth` 통과, 학교 계정 최소 배포 성공 |
| M6 | 프론트 1단계 화면 (입력·진행·결과 지도) | 배포 환경에서 fixture 목적지 결과 표시 |
| M7 | 실제 키로 영상 1개 → 5개 검증, `experiments/run_compare.py` | 실험 결과 문서 작성 |
| M8 (2단계) | Cognito, `/jobs`, `/me/*`, 유튜브 1회 연결, rerank | 소유자 확인·토큰 미저장 테스트 통과 |

---

## 12. 사람에게 확인받아야 하는 것

- Gemini 사용 허용 여부 (불허 시 M7 전에 중단하고 대체 모드 논의)
- 학교 계정의 허용 US 리전, 각 모델 ID·Converse 지원·추론 프로파일
- 학교 계정 CDK bootstrap·IAM 역할 생성·OIDC 가능 여부
- Google Cloud 프로젝트(YouTube Data API, Places, Maps JS 키) 결제·상한 설정
- YouTube 메타데이터 기반 스타일 분류·개인화의 정책 이용 범위
- 첫 검증 도시와 영상 5개

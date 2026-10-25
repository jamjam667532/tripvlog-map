# 처리 흐름 한눈에 보기 (pipeline)

요청 하나가 들어와서 지도 결과가 나오기까지를 **처리 순서대로** 적었다. 코드의 각 핸들러 맨 위 설명에도 같은 단계 번호(`[1]`, `[2-2]` 등)를 붙였다.
상세 규칙은 `docs/implementation-spec.md`, 결정 근거는 `docs/decisions/`에 있다. 기준일 2026-10-25.

## 전체 그림

```
[0] api_public ─ POST /public/jobs → 작업 생성 → Step Functions 시작
│               GET  /public/jobs/{id} → 진행 상태·결과 돌려주기 (브라우저가 몇 초마다 부름)
▼
[1] collect ── YouTube 검색 3회 → 채널당 1개 → 영상 5개 + 예비 3개
▼
[2] 영상마다 (Step Functions Map) ─────────────────────────────────────────
│   [2-1] claim ──┬ ANALYZE (처음 보는 영상) ─▶ [2-2] observe   Gemini: 영상 → 단서
│                 │                              [2-3] interpret Bedrock: 단서 → 장소 후보
│                 │                              [2-4] match     Places + 규칙: 후보 → 확정/미확정
│                 ├ REUSE  (이미 분석됨) ──────▶ 바로 끝 (Gemini·Bedrock·Places 호출 0)
│                 └ WAIT   (다른 작업이 분석 중) ▶ 30초 기다렸다 다시 [2-1]
│   어느 단계든 실패하면 [2-x] claim(fail): 그 영상만 FAILED, 다른 영상은 계속
▼
[3] aggregate(replace) ── 실패한 영상이 있으면 예비 영상 1개로 [2]를 한 번 더 (작업당 1회)
▼
[4] aggregate(aggregate) ── 채널별 집계 → 순위 → 지역 묶기 → 결과 JSON(S3) → 작업 종료

[매일] cleanup ── 만료된 캐시·좌표 삭제 (YouTube·Google 약관)   ※ 아직 미구현
[M8]  api_jobs, api_me ── 로그인 사용자 경로                    ※ 아직 미구현(빈 틀)
```

## 2단계(M8): 로그인 + 유튜브 1회 연결 (아직 미구현)

```
[M8] 로그인 (Google ID 토큰 JWT, 결정 0007-2)
  └ "유튜브 연결" → 브라우저가 짧은 수명 액세스 토큰(youtube.readonly) 받음
      → POST /me/youtube/import : 구독 채널·좋아요 영상을 1회 조회 → 여행 채널·영상 후보 반환 (토큰 저장·로그 금지, 확정 결정 3)
      → POST /me/youtube/confirm: 사용자가 고른 참고 채널·스타일만 Users.preferences에 저장
      → [4] 순위에서 참고 채널이 방문한 장소에 가중치 (rules/ranking.py REFERENCE_WEIGHT, 구현됨)
      → POST /jobs/{id}/rerank   : 모델 호출 없이 규칙으로 순위만 다시
  └ DELETE /me/youtube/connection: 유튜브 유래 데이터만 삭제
```

- 좋아요 수·조회수·구독자 수는 점수에 쓰지 않는다. "이 사용자가 어느 채널을 보는지"만 쓴다.
- `youtube.readonly`는 Google 앱 검증 대상이라, 검증 전에는 등록한 테스트 계정(최대 100개)만 쓸 수 있다.
- 상세: `implementation-spec.md` §3.3, §4.4.

## 단계별 표

| 단계 | Lambda (코드) | 입력 | 출력 | 외부 호출 | 저장 | 쓰는 규칙·클라이언트 |
| --- | --- | --- | --- | --- | --- | --- |
| **[0]** 요청 | `api_public` ([handler](../backend/functions/api_public/handler.py)) | 목적지·스타일·동행 | jobId, guestAccessToken | Step Functions 시작 | Jobs | `clients/orchestrator` |
| **[1]** 영상 고르기 | `collect` ([handler](../backend/functions/collect/handler.py)) | jobId | 영상 5개 목록 | **YouTube** (검색 3회 = 300 units) | YoutubeCache(25일), Jobs | `clients/youtube`, `rules/selection`, `rules/style_tags` |
| **[2-1]** 선점 | `claim` ([handler](../backend/functions/claim/handler.py)) | 영상 1개 | ANALYZE / REUSE / WAIT | — | VideoAnalysis | `repos/video_analysis` |
| **[2-2]** 관찰 | `observe` ([handler](../backend/functions/observe/handler.py)) | 영상 1개 | 단서 목록의 S3 키 | **Gemini** (`GEMINI_MODELS`가 있으면 3분 구간마다 1회 + 얇은 구간 다시 1회, 없으면 영상당 1회) | S3 `observation.json` | `clients/gemini`, `prompts/observe.md` |
| **[2-3]** 해석 | `interpret` ([handler](../backend/functions/interpret/handler.py)) | 단서 S3 키 | 장소 후보 S3 키 | **Bedrock** (단서 80개마다 1회, 형식 오류면 +1. 게이트웨이 출력 4,096토큰 한도) | S3 `interpretation.json` | `clients/bedrock`, `prompts/interpret.md` |
| **[2-4]** 지점 매칭 | `match` ([handler](../backend/functions/match/handler.py)) | 후보 S3 키 | 확정 장소 수 | **Places** (후보당 1회) | Places(근거), CoordCache(좌표 25일), S3 `match.json` | `clients/places`, `rules/matching`, `rules/evidence` |
| **[2-x]** 실패 기록 | `claim` action=fail | Step Functions 오류 이름 | FAILED | — | Jobs, VideoAnalysis | — |
| **[3]** 예비 영상 대체 | `aggregate` action=replace ([handler](../backend/functions/aggregate/handler.py)) | jobId | 대체 영상 또는 없음 | — | Jobs | `rules/replacement` |
| **[4]** 집계 | `aggregate` action=aggregate | jobId | 결과 JSON S3 키 | — | S3 `result.json`, Jobs | `rules/aggregation`, `rules/time_evidence`, `rules/ranking`, `rules/area`, `rules/evidence` |
| [매일] 정리 | `cleanup` | — | — | — | 만료 아이템 삭제 | (미구현) |

**누가 무엇을 결정하나** (CLAUDE.md 원칙): Gemini는 보고 적기만, Bedrock은 묶고 분류하기만, **확정·집계·순위는 규칙 코드**(`backend/shared/rules/`)가 한다.

## 단계별 입력 → 출력 예 (O5 영상, 규카츠 모토무라)

| 단계 | 예 |
| --- | --- |
| [1] | `{"videoId": "j310ARBk0G4", "channelId": "…Tv3fTg", "analysisVersion": "v1-haiku45"}` |
| [2-2] | 단서 `#62 16:46 SCREEN_TEXT "규카츠 모토무라 난바 분점 / 牛かつもと村 難波分店"`, `#63 16:56 SCREEN_TEXT "…첫 응대 직원이 매우 불친절"` |
| [2-3] | 후보 `{names: ["규카츠 모토무라","牛かつもと村"], branch_hint: "난바 분점", visit_status: VISITED, clue_refs: [62,63], ratings: {taste: POSITIVE, service: NEGATIVE}}` |
| 걸러내기 | 근거 번호 없음·범위 밖이면 버림 (`schemas/interpretation.py`). 이름 뒷받침 규칙 C(결정 0006-3)는 **미구현** |
| [2-4] | Places 검색 → 이름 유사도 0.8 이상 + "난바"가 이름·주소에 있는 곳만 → 1곳이면 CONFIRMED, 2곳 이상이면 UNCONFIRMED, 0곳이면 버림 |
| [4] | 지도 핀 "규카츠 모토무라 · 난바 분점", 방문 채널 1, 맛 긍정·서비스 부정, 근거 링크 `youtu.be/j310ARBk0G4?t=1016` |

## 데이터가 어디 남나

| 저장소 | 무엇 | 언제 지움 |
| --- | --- | --- |
| DynamoDB `jobs` | 작업 상태, 영상별 상태, 비용 지표 | — |
| DynamoDB `youtube-cache` | 검색 결과·영상 정보, 하루 검색 횟수 | 25일 |
| DynamoDB `video-analysis` | 영상별 분석 상태(선점·완료·실패) | — |
| DynamoDB `places` | placeId + 영상 기반 표기 + 근거 (Google 이름·주소는 저장 안 함) | — |
| DynamoDB `coord-cache` | placeId별 좌표 | 25일 (Google 약관) |
| DynamoDB `users` | 로그인 사용자 (M8) | — |
| S3 `analysis/{videoId}/{version}/` | observation.json, interpretation.json, match.json | — |
| S3 `results/{jobId}/result.json` | 최종 결과 | — |

같은 영상·같은 `ANALYSIS_VERSION`이면 [2-1]에서 REUSE가 되어 다음 요청부터 Gemini·Bedrock·Places를 다시 부르지 않는다. 프롬프트·모델을 바꾸면 버전을 올리고, 그러면 전부 다시 분석한다.

## 걸리는 시간 (10/25 실측)

**[2-2] 관찰 방식(2026-10-25 저녁부터, `SegmentedObserver`):** 영상을 약 3분 구간으로 잘라 3.5-flash-lite·3.1-flash-lite에 동시에 보낸다(LOW·2초에 한 장면·프롬프트 v2·재생 위치 "MM:SS"). 모델마다 분당 14회까지만 보내고 넘치는 구간은 다음 1분으로 미룬다. 실패·얇은 구간은 3.5-flash-lite로 한 번 더 보내 합친다. 근거: `experiments/results/gemini-observe-history.md`.

| 측정 | 시간 |
| --- | --- |
| 실험 스크립트, 영상 1개(구간 동시) | Gemini 15~35초 |
| 실험 스크립트, 영상 5개(두 모델) | 마지막 영상까지 35~48초 |
| **로컬 서버 실제 요청 1건(오사카, 영상 5개, 22:03)** | **첫 장소 91초, 전체 223초**, 5개 모두 성공, 장소 18곳 |

- 실제 요청이 실험보다 느린 이유: 구간 요청이 약 32회 + 다시 보내기라 두 모델 합계 분당 28회를 넘어 일부가 1분씩 기다린다. 해석은 영상당 7~37초, 매칭 1~27초.
- 이전 방식(3.8-flash 통째로, 하나씩)은 영상 5개 약 12분.
- 이미 분석한 영상은 다음 요청부터 바로 쓴다(같은 `ANALYSIS_VERSION`).

## 쓰지 않는 것 (2026-10-25 정리)

| 대상 | 처리 |
| --- | --- |
| Nova Micro 스타일 태깅 | **삭제.** 학교 게이트웨이에 없다. 스타일은 `rules/style_tags.py` 키워드만 |
| 업로드 모드 (Nova Lite + Transcribe) | **삭제.** 영상 파일이 필요해 확정 결정 5와 YouTube 정책에 어긋난다(결정 0006 대안) |
| Claude 3.5 Sonnet v2 | 쓰지 않음 |
| GPT-5.6 Luna (`bedrock-gpt-5.6-luna`) | 파이프라인에는 없음. M7 비교 실험에서만 |
| `api_jobs`, `api_me` | M8까지 빈 틀로 둔다 |

## 폴더 지도

```
backend/
  functions/<단계>/handler.py   단계별 Lambda. clients·repos·rules를 조합만 한다
  shared/clients/   외부 API: youtube[1] gemini[2-2] bedrock[2-3] places[2-4] orchestrator[0] secrets(키 읽기)
  shared/rules/     규칙(순수 함수): selection·style_tags[1] matching·evidence[2-4] replacement[3]
                    aggregation·time_evidence·ranking·area·evidence[4]
  shared/repos/     DynamoDB·S3 읽기/쓰기
  shared/schemas/   모든 입출력 Pydantic 모델. events.py = 단계 사이 이벤트 계약
  shared/prompts/   observe.md[2-2], interpret.md[2-3]
  tests/integration/pipeline.py   Step Functions 흐름을 테스트에서 흉내 (M5 ASL과 같은 순서)
experiments/gemini_observe/       Gemini 관찰 실험 (probe.py, view.py)
```

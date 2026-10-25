# AGENTS.md: 여러 에이전트·팀원이 함께 작업하기 위한 안내

이 저장소는 팀원 2명과 여러 코딩 에이전트(Claude Code, Codex, Qwen Code 등)가 함께 작업한다. 이 파일은 **누가 어떤 도구로 들어오든 같은 기준으로 일하게** 하려고 둔다.

> 기준일: 2026-10-25 · 마지막 완료 마일스톤: **M4** · 다음: **M5** (M6 프론트는 다른 세션이 `claude/m6-frontend`에서 진행 중) · 결정 0008 제안 확인 대기

---

## 0. 먼저 읽을 것 (순서대로)

| 순서 | 파일 | 내용 |
| --- | --- | --- |
| 1 | `AGENTS.md` (이 파일) | 현재 상태, 협업 규칙, 작업 분담 |
| 2 | [`CLAUDE.md`](CLAUDE.md) | **프로젝트 규칙 원본.** 확정 결정, 코딩 규칙, 금지 사항. 도구 이름과 상관없이 모든 에이전트가 따른다 |
| 3 | [`docs/pipeline.md`](docs/pipeline.md) | **처리 순서 한눈에 보기.** 코드 첫 줄의 `[1]`, `[2-2]` 같은 단계 번호의 뜻 |
| 4 | [`docs/implementation-spec.md`](docs/implementation-spec.md) | 구현 명세 (API 계약, 데이터 모델, 파이프라인, 마일스톤) |
| 5 | [`docs/decisions/`](docs/decisions/) | 확정된 결정 기록. 명세와 다르면 결정 기록이 최신이다 |
| 6 | [`docs/기획서.md`](docs/기획서.md) | 기획 배경 (필요할 때만) |

규칙이 충돌하면 **CLAUDE.md → docs/decisions → implementation-spec → 기획서** 순서로 따른다. 이 파일은 CLAUDE.md를 요약·보조할 뿐이고, 내용이 다르면 CLAUDE.md가 맞다.

---

## 1. 프로젝트 한 줄 요약

목적지(해외 도시)를 입력하면 한국어 여행 브이로그 최대 5개(서로 다른 채널)를 골라 **Gemini로 관찰**하고 **Bedrock으로 해석**해, 여러 채널에서 확인된 장소 방문·평가·방문 시간대 근거를 Google 지도에 보여주는 서버리스 웹 서비스. 졸업 프로젝트(AWS Bedrock 활용 필수).

**AI는 결론을 내리지 않는다.** Gemini는 관찰만, Bedrock은 해석만 하고, 지점 확정·집계·순위는 `backend/shared/rules`의 규칙 코드가 한다.

---

## 2. 현재 상태

| 마일스톤 | 내용 | 상태 |
| --- | --- | --- |
| M0 | 저장소 골격, Makefile, docker compose, CI, pre-commit | ✅ 완료 |
| M1 | `shared/schemas`: Pydantic 모델 + fixture 계약 테스트 | ✅ 완료 |
| M2 | `shared/rules`: matching, aggregation, time_evidence, ranking, replacement | ✅ 완료 |
| M3 | `shared/clients`: youtube, gemini, bedrock, places + `tests/fakes` | ✅ 완료 |
| M4 | Lambda 핸들러 + DynamoDB Local 통합 테스트 | ✅ 완료 |
| **M5** | 배포: zip 빌드(CI) + Step Functions ASL + 콘솔 runbook + 첫 배포 (결정 0007) | ⏳ **다음** |
| M6 | 프론트 1단계 화면 | 🔄 진행 중 (`claude/m6-frontend`, 다른 세션) |
| M7 | 실제 키 검증, 규칙 vs Bedrock 비교 실험 | 대기 |
| M8 | 로그인·개인화 (2단계) | 대기 |

- 테스트: pytest 265개(DynamoDB Local·moto 양쪽), vitest 1개 통과.
- 저장소: https://github.com/jamjam667532/tripvlog-map (공개)
- 실제 API는 **실험 스크립트에서만** 호출했다(Gemini·YouTube, 2026-10-21~25, `experiments/gemini_observe/`, 결과는 `experiments/results/`). Bedrock·Places는 아직 호출하지 않았다. 테스트에서는 절대 호출하지 않는다.

### 구현돼 있는 것 (재사용할 것)

```
backend/shared/
├─ schemas/      데이터 형식. 모든 외부 입출력은 여기 모델로 검증한다
│   ├─ api.py            API 요청·응답 (CreateJobRequest, GetJobResponse, ErrorResponse …)
│   ├─ items.py          DynamoDB 아이템 6종 (JobItem, VideoAnalysisItem, PlaceEvidenceItem …)
│   ├─ observation.py    Gemini 출력 (ObservationResult)
│   ├─ interpretation.py Bedrock 출력 (InterpretationResult, link_to_observation)
│   ├─ result.py         결과 JSON (JobResult)
│   ├─ places.py         Places 검색 결과 (PlaceHit, 메모리 전용·저장 금지)
│   └─ youtube.py        영상 메타 (VideoMeta)
├─ rules/        순수 함수. 외부 호출 없음
│   ├─ matching.py       지점 매칭 → CONFIRMED / UNCONFIRMED / DISCARDED
│   ├─ aggregation.py    채널당 1표 집계, job_status
│   ├─ time_evidence.py  시간대 근거 요약, recommend 판단
│   ├─ ranking.py        순위 (인기 지표 입력 없음)
│   └─ replacement.py    실패 영상 대체 선택
├─ clients/      외부 API 호출은 여기에만
│   ├─ youtube.py  gemini.py  bedrock.py  places.py   (각각 Protocol + 실제 구현)
│   ├─ secrets.py  서버 키 읽기 (지금 SSM → M5에서 설정 버킷 keys.json으로, 결정 0007-3)
│   └─ http.py     테스트에서 바꿔 끼우는 HTTP 전송
├─ prompts/      observe.md (Gemini), interpret.md (Bedrock)
├─ repos/        Jobs(낙관적 잠금), VideoAnalysis(조건부 선점), Places, CoordCache, YoutubeCache, S3 BlobStore
└─ settings.py   환경 변수 설정 (값 목록은 infra/config.py, 콘솔에서 Lambda에 입력)

backend/functions/<name>/handler.py   collect, claim, observe, interpret, match, aggregate, api_public 구현 (M4)
                                      api_jobs, api_me(M8), cleanup(M5 이후)은 아직 껍데기
backend/tests/integration/pipeline.py Step Functions 흐름 흉내 (M5 ASL도 같은 순서·이벤트)
backend/tests/fakes/                  가짜 클라이언트 (FakeYouTube, FakeGemini, FakeBedrock, FakePlaces)
backend/tests/fixtures/contracts/     스키마별 valid_*.json / invalid_*.json (파일만 추가하면 자동 검사)
infra/config.py                       모델 ID·리전·한도 (TODO(verify) 값은 사람이 콘솔에서 확인해 넣는다)
```

---

## 3. 환경과 명령

필요한 도구: `uv`(Python 3.12를 대신 설치해 줌), Node 24 이상, Docker, `make`.

```bash
make install   # uv sync + npm ci + pre-commit 훅 설치 (처음 한 번)
make lint      # ruff, ruff format --check, mypy(strict), eslint, tsc
make test      # pytest + vitest
make local     # docker compose up (DynamoDB Local :8000)
make synth     # cdk synth (M5에서 CDK 제거 예정, 결정 0007-5)
make fmt       # ruff 자동 수정·포맷
```

- **커밋 전에 `make lint`와 `make test`가 통과해야 한다.** pre-commit 훅(ruff, gitleaks)이 커밋을 막으면 우회하지 말고 고친다.
- mypy는 aws-cdk-lib 때문에 메모리를 약 3 GB 쓴다. 여러 에이전트가 동시에 돌리면 느려질 수 있다.
- Python 명령은 항상 `uv run …`으로 실행한다(가상환경 자동 사용).

---

## 4. 반드시 지킬 규칙 (CLAUDE.md 요약)

**하지 말 것**
- 일정·동선·경로·기간 입력 관련 코드나 UI
- 조회수·좋아요 수·구독자 수·업로드일을 장소 점수에 사용 (검색 정렬에만 가능)
- Google 응답의 이름·주소·카테고리를 DB·S3에 저장 (장소 ID와 25일 임시 좌표만)
- 영상 내려받기(yt-dlp 등). Gemini에는 공개 YouTube URL만
- Places 응답을 Bedrock에 넘기기
- 테스트에서 실제 유료 API 호출. `backend/tests/fakes`와 fixture를 쓴다
- 쿠버네티스·젠킨스·EC2 상시 서버 추가
- 로그에 토큰, guestAccessToken 원문, Places 원문 응답, 좌표 남기기

**할 것**
- 모든 외부 입출력은 `shared/schemas`의 Pydantic 모델로 검증. dict를 그대로 흘려보내지 않는다
- 외부 API 호출은 `shared/clients`에만. 핸들러는 clients·repos·rules를 **조합만** 한다
- 비즈니스 규칙은 `shared/rules`에 순수 함수로 두고 단위 테스트를 붙인다
- 근거가 없으면 `null` / `NONE` / `UNKNOWN`. 추측으로 채우지 않는다
- 영상 재생 위치(`videoTimeRange`, 초)와 실제 방문 시각(`localClockTime`)을 섞지 않는다
- 사용자는 JWT `sub`로만 결정한다. 요청 본문의 userId를 믿지 않는다
- Step Functions 단계 사이에는 ID·상태·S3 키만 넘긴다 (256 KiB 제한)
- 모델 ID·리전·한도는 하드코딩하지 않고 `infra/config.py` → 환경 변수로
- 커밋 메시지는 Conventional Commits: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `ci:`

---

## 5. 멀티 에이전트 협업 규칙

### 5.1 브랜치와 PR
- `main`에 직접 push하지 않는다. 작업마다 브랜치를 만든다: `<종류>/<주제>` (2026-10-25부터)
  - 종류: `feature/`(기능), `fix/`(버그), `docs/`(문서·결정), `exp/`(실험), `chore/`(설정·CI)
  - 예: `feature/m5-deploy`, `feature/m6-frontend`, `fix/collect-dest-filter`, `exp/gemini-segments`
  - 누가 했는지는 브랜치 이름 대신 PR 설명과 커밋에 남긴다. 이전 `claude/…` 브랜치는 병합되면 지운다.
- PR 하나에 작업 ID 하나. 작게 자주 올린다.
- **CI가 초록이어야 병합한다.** 다른 사람(또는 다른 에이전트)의 PR을 리뷰한 뒤 병합한다.
- 병합 전에 최신 `main`을 받아(`git pull --rebase origin main`) 충돌을 해결하고 `make lint test`를 다시 돌린다.

### 5.2 파일 소유 범위
충돌을 줄이기 위해 **작업 ID마다 고칠 수 있는 파일을 정한다**(§6 표). 범위 밖 파일을 고쳐야 하면:

| 파일 | 규칙 |
| --- | --- |
| `backend/shared/schemas/**` | 모든 작업이 의존한다. 고치려면 **별도 PR**로 먼저 올리고 PR 제목에 `[schema]`를 붙인다. 필드 삭제·이름 변경은 금지(추가만), 필요하면 결정 제안부터 |
| `backend/shared/rules/**` | 결정 0002·0003에 묶여 있다. 동작을 바꾸려면 결정 제안부터 |
| `backend/shared/clients/**` | 버그 수정만. 인터페이스(Protocol) 변경은 별도 PR |
| `backend/tests/fakes/**` | 기능 추가는 가능, 기존 동작 변경은 별도 PR |
| `infra/config.py` | 값 추가만. `TODO(verify)` 값은 사람만 채운다 |
| `docs/implementation-spec.md`, `CLAUDE.md` | 결정이 확정된 뒤에만 고친다 |

### 5.3 명세에 없는 결정이 필요할 때
1. 임의로 정하지 않는다.
2. `docs/decisions/NNNN-<제목>.md`에 **제안** 파일을 만든다: 문제, 기본안, 대안, 영향 받는 코드.
3. 번호가 겹치지 않게 PR 제목에 번호를 적고, 최신 `main`의 마지막 번호 + 1을 쓴다. 겹치면 나중에 병합하는 쪽이 번호를 올린다.
4. 코드는 기본안으로 구현하되 `TODO(decision NNNN)`을 남기고, PR 설명에 "사람 확인 필요"라고 적는다.
5. 사람이 확정하면 결정 파일 상태를 `확정`으로 바꾸고 명세에 반영한다.

예시는 [0002](docs/decisions/0002-M1-스키마-빈틈.md), [0003](docs/decisions/0003-M2-규칙-빈틈.md)을 본다.

### 5.4 PR 설명 형식

```markdown
## 작업
M4-1 collect 핸들러

## 변경
- backend/functions/collect/handler.py: …
- backend/tests/integration/test_collect.py: …

## 확인
- [ ] make lint 통과
- [ ] make test 통과 (새 테스트 N개)
- [ ] 유료 API 호출 없음 (fakes 사용)
- [ ] 로그에 토큰·좌표·Places 원문 없음

## 결정
- 없음 / 제안: docs/decisions/NNNN-… (사람 확인 필요)
```

### 5.5 에이전트에게
- 작업을 시작하면 이 파일 §6 표의 담당 칸에 이름을 적는 커밋을 먼저 올려 작업을 선점한다.
- 끝나면 §2 상태 표와 §6 상태를 갱신한다.
- 모르는 값(모델 ID, 한도, 정책 허용 여부)은 추측해서 넣지 말고 `TODO(verify)`로 두고 사람에게 묻는다.
- 이미 있는 schemas·rules·clients·fakes를 먼저 찾아 쓴다. 비슷한 것을 새로 만들지 않는다.

---

## 6. 브랜치 현황 (2026-10-25, 아직 아무것도 push·병합하지 않음)

`main`에는 M3까지만 있다. 그 뒤 작업은 아래처럼 **차례로 쌓인 로컬 브랜치**에 있다. 이어서 작업할 때는 맨 끝 브랜치에서 새 브랜치를 딴다.

| 순서 | 브랜치 | 내용 |
| --- | --- | --- |
| 1 | `claude/m4-0-repos` … `claude/m4-6-e2e` | M4 (repos, 핸들러 6개, end-to-end 테스트). M4 분담표는 git 기록에 있다 |
| 2 | `claude/0006-observe-quality` | 결정 0004·0006·0007 확정, Gemini 실험 스크립트·기록, CloudShell 스크립트 초안 |
| 3 | **`feature/observe-pipeline`** (맨 끝, GitHub에 있음. 옛 이름 `claude/pipeline-doc`) | `docs/pipeline.md`, 단계 번호 라벨, Nova 등 못 쓰는 모델 정리, 문서 갱신 |
| 별도 | `claude/m6-frontend` | `main`에서 딴 프론트 작업(다른 세션). 병합 전에 3번 위로 rebase 필요 |

M4 완료 시 "반드시 들어가야 할 테스트"(같은 영상 동시 요청 → Gemini 1회, 토큰 불일치 404, 영상 1개 실패 → PARTIAL)는 모두 통과한다.

---

## 7. 열린 질문 (사람이 답할 것)

| 질문 | 관련 |
| --- | --- |
| 결정 0008 제안 확정 (실시간 빠른 모드·5개 동시로 1분 안에 지도 표시, 목적지 무관 영상 거르기, 분석 결과 계속 재사용) | M5·M6 |
| 학교 LLM 게이트웨이: 구조화 출력 지원, Lambda(서울)에서 연결, 키 한도 (결정 0007-1 TODO) | M5·M7 |
| Gemini 사용 허용 여부 (불허 시 M7 전에 대체 모드 논의) | spec §12 |
| 학교 계정에서 콘솔로 테이블·함수·상태 머신 생성 권한 (첫 배포에서 확인) | M5 |
| 설명란 지도 짧은 링크 리다이렉트 사용: Maps 약관 (결정 0006-6) | M7 |
| Google Cloud 결제·상한 설정 | M7 |
| 첫 검증 도시와 영상 5개 (시연 도시 겸용, 오사카 유력) | M7 |

---

## 8. 확정된 결정 한눈에 보기

| 번호 | 핵심 |
| --- | --- |
| [0001](docs/decisions/0001-핵심-결정.md) | 동선·일정 없음, 로그인 선택(경로 분리), OAuth 토큰 미저장, guestAccessToken 해시만 저장, 시간 근거 4종 구분 (Bedrock US 단일 리전은 0007이 대체) |
| [0002](docs/decisions/0002-M1-스키마-빈틈.md) | SCENE은 DAY/NIGHT만 · 영상 상태 PENDING/ANALYZING 추가 + 조회 응답 `videos` · YoutubeCache 필드 · 결과 `name`은 영상 기반 표기, 화면 지점명은 Google에서 실시간 · 실패 영상은 Bedrock 1회 재요청 → 예비 영상 대체(작업당 1개) |
| [0003](docs/decisions/0003-M2-규칙-빈틈.md) | 평가는 VISITED만 · 방문 기반 시간 근거는 VISITED만(CREATOR_TIP 예외) · 대기 방향은 `ratings.wait` · 대체 성공 시 SUCCEEDED · 스타일↔분류 매핑 · 언급만 된 장소는 순위 제외 |
| [0004](docs/decisions/0004-M4-핸들러-빈틈.md) | claim 별도 Lambda(실패 기록 포함) · 대체 영상은 aggregate · 영상별 매칭 요약 S3 · 좌표 만료 장소는 지도에서 제외 · YouTube 검색 하루 90회 · jobId는 requestId에서 결정적 생성 |
| [0006](docs/decisions/0006-관찰-품질.md) | 관찰 재생 위치는 "MM:SS" 문자열 · 프롬프트 v2 + 배경 간판 금지 · 이름 뒷받침 규칙 C(약하면 미확정) · 지어낸 단서 지표 · Gemini 재시도·하루 예산 18·길이 30분 · 설명란·고정 댓글 근거 · LOW·전체 영상 |
| [0007](docs/decisions/0007-학교-AWS-계정-제약.md) | 서울 리전 · Bedrock은 학교 게이트웨이(`bedrock-haiku`) · 1단계 게스트만, M8은 Google ID 토큰 JWT(Cognito 없음) · 키는 설정 버킷 · `sgu-clicktotrip-` 접두사 · 배포는 zip + 콘솔 직접 |

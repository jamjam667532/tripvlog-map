# 코드 라벨링 기획서

> 대상: 이 작업을 넘겨받는 에이전트·팀원. 작성 2026-10-25.
> 목적: 코드 파일만 열어도 **처리 흐름의 몇 번째 단계인지** 바로 알 수 있게 한다. 흐름 전체는 [`docs/pipeline.md`](pipeline.md).

## 1. 시작 지점

- **브랜치:** `feature/observe-pipeline`에서 새 브랜치를 딴다(예: `codex/label-1-backend`). `main`·`claude/m6-frontend`에는 M4 코드가 없어 핸들러가 빈 틀이다. 거기서 시작하면 안 된다.
- **이미 된 것(1차, 커밋 `6b067c9`):** 아래 26개 파일의 docstring 첫 줄에 단계 번호를 붙였다.
  - `backend/functions/*/handler.py` 10개
  - `backend/shared/clients/` 6개(orchestrator, youtube, gemini, bedrock, places, secrets)
  - `backend/shared/rules/` 9개
  - `backend/shared/schemas/events.py`
- 이 기획서는 **나머지 파일**과 **규칙 정리**를 맡긴다.

## 2. 단계 번호

| 번호 | 단계 | 대표 파일 |
| --- | --- | --- |
| `[0]` | 요청 받기·결과 조회 | `functions/api_public` |
| `[1]` | 영상 고르기 | `functions/collect` |
| `[2-1]` | 선점 (새로 분석 / 재사용 / 대기) | `functions/claim` |
| `[2-2]` | 관찰 (Gemini) | `functions/observe` |
| `[2-3]` | 해석 (Bedrock) | `functions/interpret` |
| `[2-4]` | 지점 매칭 (Places + 규칙) | `functions/match` |
| `[2-x]` | 영상 실패 기록 | `functions/claim` action=fail |
| `[3]` | 예비 영상 대체 | `functions/aggregate` action=replace |
| `[4]` | 집계·결과 JSON | `functions/aggregate` |
| `[매일]` | 만료 데이터 정리 | `functions/cleanup` |
| `[M8]` | 로그인 경로 | `functions/api_jobs`, `functions/api_me` |
| `[공통]` | 여러 단계가 같이 쓰는 기반 (특정 단계에 묶이지 않음) | `shared/settings.py`, `clients/http.py` 등 |
| `[F-…]` | 프론트 화면 단계 (아래 4절) | `frontend/src/**` |

결정 0008이 확정돼 흐름이 바뀌면 번호표를 `pipeline.md`와 이 표에서 **같이** 고친다. 번호는 `pipeline.md`를 기준으로 한다.

## 3. 형식 규칙

**Python:** 모듈 docstring의 **첫 줄 맨 앞**에 번호를 붙이고 공백 하나를 둔다. 여러 단계에서 쓰면 이어 붙인다.
```python
"""[2-4] match: 해석 후보를 Places Text Search 결과와 규칙으로 맞춘다 (spec §5.4).
"""[2-4][4] 해석 후보 → 근거 아이템 값 (결정 0004-7).
"""[공통] 환경 변수 설정 …
```
- 첫 줄이 100자를 넘으면(ruff E501) 뒷문장을 다음 줄로 내린다. 문장을 지우거나 줄이지 않는다.
- docstring이 없는 파일은 한 줄 docstring을 새로 단다: `"""[N] <파일이 하는 일 한 문장>."""`
- **번호 고르는 기준:** 그 파일을 **import하는 핸들러**의 단계. 확인 명령:
  `git grep -n "from shared.repos.places import" -- backend/functions` → 쓰는 핸들러 목록 → 그 단계 번호들.
  핸들러가 3개 이상 쓰면 `[공통]`.

**TypeScript (프론트):** 파일 맨 위 한 줄 주석.
```ts
// [F-2] 진행 화면: 영상별 상태(대기·분석 중·완료)를 몇 초마다 조회해 보여 준다.
```

**Markdown 프롬프트(`backend/shared/prompts/*.md`)는 라벨링하지 않는다.** `clients/prompts.py`가 파일을 그대로 모델에 보내므로 주석도 프롬프트가 된다(결과와 `ANALYSIS_VERSION`이 바뀐다). 단계는 `pipeline.md` 폴더 지도에만 적는다.

## 4. 맡길 범위 (2차)

| 순서 | 대상 | 파일 | 비고 |
| --- | --- | --- | --- |
| 1 | repos | `backend/shared/repos/*.py` 8개 | jobs·blobs는 여러 단계 → `[공통]`일 가능성이 큼. import로 확인 |
| 2 | schemas | `backend/shared/schemas/*.py` (events.py 제외) | api `[0]`, youtube `[1]`, observation `[2-2]`, interpretation `[2-3]`, places·match `[2-4]`, result `[4]`, items·base·common `[공통]` |
| 3 | 나머지 clients | `ai_schema.py`, `errors.py`, `http.py`, `prompts.py` | 대부분 `[공통]` 또는 `[2-2][2-3]` |
| 4 | 설정·스크립트 | `backend/shared/settings.py`, `scripts/*.py`, `infra/config.py` | `[공통]` |
| 5 | 테스트 | `backend/tests/integration/test_*.py`, `backend/tests/unit/**/test_*.py` | 테스트하는 대상의 번호. `pipeline.py`는 `[0]~[4]` |
| 6 | 가짜 클라이언트 | `backend/tests/fakes/*.py` | 바꿔 끼우는 클라이언트의 번호 |
| 7 | 프론트 | `frontend/src/**` (M6, `claude/m6-frontend` 병합 **후**) | `[F-1]` 입력, `[F-2]` 진행, `[F-3]` 지도·결과. 번호표를 `pipeline.md`에 추가 |
| 8 | 실험 | `experiments/gemini_observe/*.py` | `[2-2] 실험` |

`__init__.py`, `__pycache__`, fixture JSON은 하지 않는다.

## 5. 하지 말 것

- **동작을 바꾸지 않는다.** docstring·주석만 고친다. import 순서, 코드, 테스트 기댓값은 그대로.
- 기존 설명 문장을 지우거나 고쳐 쓰지 않는다(번호만 앞에 붙인다).
- `infra/config.py`의 `TODO(verify)` 값, 특히 `GEMINI_MODEL`은 건드리지 않는다(사람이 채우는 값).
- `backend/shared/schemas/**`를 고치는 PR은 원래 `[schema]` 별도 PR 규칙이 있다. 라벨링은 docstring만 바꾸므로 같은 PR에 넣어도 되지만 PR 제목에 `[schema-docs]`를 붙인다.
- 프론트 파일은 `claude/m6-frontend`가 병합되기 전에는 손대지 않는다(충돌).

## 6. 완료 확인

```bash
make lint && make test        # 동작이 안 바뀌었는지 (pytest 265개 그대로 통과)
# 라벨 없는 Python 모듈 찾기: 아래가 아무것도 안 나와야 한다
for f in $(git ls-files 'backend/**/*.py' 'scripts/*.py' 'infra/*.py' 'experiments/**/*.py' | grep -v __init__); do
  head -1 "$f" | grep -q '^"""\[' || echo "라벨 없음: $f"
done
```
- `docs/pipeline.md` "폴더 지도" 절에 새로 붙인 번호가 반영됐는지 본다.
- AGENTS.md §2 상태 표 밑에 "라벨링 2차 완료"를 한 줄 적는다.

## 7. PR

- 제목: `docs: label backend modules by pipeline step (2nd pass)`
- PR 하나에 4절의 1~6번(백엔드), 프론트(7번)는 별도 PR.
- 설명에 "동작 변경 없음, docstring·주석만"과 6절 확인 결과를 적는다.

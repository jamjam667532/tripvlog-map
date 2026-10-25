# 진행 보고: Gemini 관찰 최적화와 앱 반영 (2026-10-25)

> 보내는 쪽: Gemini 관찰 최적화 세션. 받는 쪽: 처리 흐름 정리 세션(라벨링·`pipeline.md` 담당), 발표 검토 세션.
> 브랜치: **`feature/observe-pipeline`** (GitHub에 있음). 이 문서에 나온 모든 숫자의 원본: `experiments/results/2026-10-21-gemini-observe.md`(실행별 표), 요약: `experiments/results/gemini-observe-history.md`.

## 1. 한 줄 요약

영상을 통째로 Gemini에 보내던 방식(영상 5개 약 12분, 평가 문장 들쭉날쭉)을 **3분 구간으로 잘라 가벼운 모델 두 개에 동시에 보내는 방식**으로 바꿨다. 실험에서는 영상 5개가 35~48초, 정답 영상 품질은 예전과 같은 수준(평가 11~12/13). 앱(로컬 서버)에 넣어 실제 요청 1건을 돌리면 **첫 장소 91초, 전체 223초, 5개 모두 성공, 장소 18곳**.

## 2. 오늘 바뀐 코드 (`backend/`)

| 단계 | 파일 | 바뀐 것 | 근거 결정 |
| --- | --- | --- | --- |
| [1] 영상 고르기 | `shared/rules/selection.py`, `functions/collect/handler.py` | 30분 넘는 영상 제외, 제목·설명란에 목적지(별칭 `DESTINATION_ALIASES`)가 없는 영상 제외 | 0006-5(확정), 0008-4(팀 동의) |
| [2-2] 관찰 | `shared/clients/gemini.py` | **`SegmentedObserver`**: 약 190초 구간, 동시 호출, 모델별 분당 14회 `RateLimiter`, 실패·얇은 구간(1분당 단서 2개 미만 또는 출력이 다른 구간 중앙값의 1/4 미만) 3.5-flash-lite로 다시 보내 합침, 같은 5초·같은 글자 중복 제거. 기존 `GeminiYouTubeObserver`도 유지 | 0008(제안) |
| [2-2] 관찰 | `shared/schemas/observation.py`, `shared/prompts/observe.md` | 출력은 `ObservationWire`(재생 위치 "MM:SS") → 코드에서 초로 바꿔 `ObservationResult`로 검증. 영상 길이를 넘으면 잘못된 출력. 프롬프트 v2 + 배경 간판 금지 문장 | 0006-1·2(확정) |
| [2-2] 관찰 | `functions/observe/handler.py`, `shared/settings.py` | `GEMINI_MODELS`(쉼표, 선호 순)가 있으면 구간 관찰기. `GEMINI_SEGMENT_SEC`, `GEMINI_FPS`, `GEMINI_RPM`. 영상 길이는 YoutubeCache에서 | 0008(제안) |
| [2-3] 해석 | `shared/clients/bedrock.py` | **`ChunkedInterpreter`**: 단서 80개씩 나눠 해석하고 `clue_refs`를 전체 번호로 되돌림. 학교 게이트웨이가 출력을 **4,096토큰에서 자르는** 것을 확인(finish_reason=length)해서 필요해졌다 | 새 발견 |
| 로컬 서버 | `backend/local/server.py` | 기본값: `gemini-3.5-flash-lite,gemini-3.1-flash-lite`, 구간 190초, fps 0.5, 분당 14. 분석 버전 `local-v2-seg190-…` | — |
| 프론트 | `frontend/` (`claude/local-server`에서 합쳐 옴) | 진행 중 결과 화면, 단계 흉내 가짜 API | 프론트 세션 작업 |

테스트: pytest 287개 통과(구간 나누기·합치기·얇은 구간·분당 제한·MM:SS·해석 나누기 테스트 추가), mypy·ruff 통과.

## 3. 실험으로 알게 된 것 (중요한 것만)

1. **응답 시간 대부분은 출력을 쓰는 시간이다.** 생각 수준을 낮추면 빨라지지만 그만큼 덜 적는다(평가 문장 0~3/13).
2. **긴 영상을 통째로 주면 뒤쪽을 버린다.** 3분 구간으로 나누면 가벼운 모델도 끝까지 적는다. 정답 영상 3.5-flash-lite 6구간: 장소 10/11, 평가 11~12/13, 우편번호 6/6.
3. **3분보다 긴 구간(4분)은 다른 영상에서 크게 나빠진다.** 정답 영상만 보면 괜찮아 보여 착각하기 쉽다.
4. **3.1-flash-lite는 평가 자막을 놓친다**(4~6/9, 3.5-flash-lite 8~9/9). 생각 수준을 올려도 그대로.
5. **구간의 약 9%가 갑자기 짧게 끝난다.** 다시 보내기로 메운다.
6. **3.8-flash는 구간으로 나눠도 느리다**(구간 하나 168~220초). 실시간에 못 쓴다.
7. **무료 한도는 모델마다 따로**(3.5-flash-lite·3.1-flash-lite 각각 분당 15·하루 500). 같은 API 키를 쓰는 세션·실험은 한도를 나눠 쓴다. 3-flash-preview는 하루 20이라 오늘 소진됐다.

## 4. 실제 앱에서 돌린 결과 (로컬 서버, 오사카, 22:03)

| 영상 | 관찰 | 해석 | 매칭 |
| --- | --- | --- | --- |
| dCVRISJWTHw | 72초 | 7초 | 4초 |
| 1wwzvm1FeG8 | 75초 | 9초 | 3초 |
| QP9NS7NjLaE | 68초 | 16초 | 8초 |
| DK0XrbsnXUo | 83초 | 37초 | 27초 |
| pvWh4_bm0J8 | 185초 | 24초 | 10초 |

- 전체 223초, 첫 장소 91초. 장소 18곳(야키니쿠 후지모토, 구로몬 시장, 우메다 스카이빌딩, 덴덴타운 등).
- 같은 서버의 첫 실행 두 번은 실패가 많았다: 해석 출력 잘림(→ `ChunkedInterpreter`로 해결), 59·53분 영상 선택(→ 30분 상한으로 해결).

## 5. 남은 문제

| 문제 | 상태 / 다음 할 일 |
| --- | --- |
| 실제 요청이 실험보다 느림(223초) | 구간 요청이 분당 28회를 넘어 기다림. 이미 분석한 영상 재사용, 단계적 화면(결정 0008 2-2)으로 기다림을 볼거리로 |
| 모든 장소가 "5개 채널 중 1개" | 영상 5개로는 겹침이 드묾. 미리 분석해 둔 영상을 함께 집계하면 늘어남 |
| 평가 표시 확인 안 됨 | 결과 화면에서 직접 확인 필요 |
| 지역 묶음 이름 "지역 1~6" | `rules/area.py`가 이름을 붙이지 않음 |
| 조회 응답의 새 필드(구간 진행, 확인 중 칩, 영상 제목) | 결정 0008 2-3, `[schema]` 별도 PR 예정 |
| 이름 뒷받침 규칙 C | 결정 0006-3 확정, 미구현 |
| 결정 0008 | 아직 "제안". 구간 방식·모델 배정·마감 시간 확정 필요 |

## 6. 처리 흐름 정리 세션에 부탁

- `docs/pipeline.md`는 이 보고대로 갱신해 두었다([2-2]·[2-3] 행, "걸리는 시간" 절). 라벨링 2차(`docs/labeling-plan.md`)를 할 때 새 클래스(`SegmentedObserver`, `RateLimiter`, `ChunkedInterpreter`)와 `schemas/observation.py`의 `ObservationWire`도 `[2-2]`·`[2-3]`로 표시해 달라.
- `claude/label-2-backend` 브랜치는 이 브랜치보다 앞선 코드에서 딴 것이면, 합칠 때 `shared/clients/gemini.py`·`bedrock.py`·`schemas/observation.py`가 충돌할 수 있다. 이 브랜치 위로 다시 따는 게 안전하다.

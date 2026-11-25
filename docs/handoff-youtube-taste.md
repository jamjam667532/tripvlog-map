# 인수인계: 유튜브 구독·좋아요 취향 분석 (2026-11-19)

> 브랜치 `feature/youtube-taste` (`feature/aws-first-deploy` 위에 쌓음). 결정 기록: `docs/decisions/0010-유튜브-취향-분석.md`(확정).
> 발표 지적 2(차별점)에 대한 답이고, 지적 3(비용)을 먼저 지키도록 설계했다.

## 1. 한 줄 요약

로그인한 사용자가 유튜브를 연결하면 구독·좋아요를 **한 번** 읽어 여행 채널 후보와 스타일 비율을 보여 주고, **사용자가 고른 것만** 저장한다. 저장된 채널은 순위 가중치와, 그 채널의 이 도시 영상을 요청 5개 중 최대 2개로 넣는 데 쓴다(이미 분석된 것 먼저, 없으면 실시간 분석. 결정 0010 개정 2026-11-25).

## 2. 된 것 (테스트 338개 통과, 실제 API 호출 없음)

| 파일 | 내용 |
| --- | --- |
| `functions/api_me/handler.py` | `GET`·`PATCH /me/preferences`, `POST /me/youtube/import`, `POST /me/youtube/confirm`, `DELETE /me/youtube/connection` |
| `shared/rules/taste.py` | 여행 후보 거르기, Bedrock 근거 확인(원문에 없으면 UNKNOWN), 스타일 비율, `personal_first`(개인 영상 최대 2개, 채널당 1개) |
| `shared/clients/youtube.py` | `channels`, `uploads`(1 unit), `YouTubeUserApi`(내 구독·좋아요, Bearer 토큰, 저장 안 함) |
| `shared/clients/taste.py`, `shared/prompts/taste.md` | 게이트웨이로 채널 라벨 제안. 30채널씩 나눠 호출, 형식 오류 1회 재요청 |
| `shared/clients/bedrock.py` | 게이트웨이 호출을 `GatewayChat`으로 분리(해석과 공용). 해석 동작은 그대로 |
| `shared/repos/users.py`, `caches.py` | Users 읽기·쓰기, 채널 라벨 캐시(`CHANNEL#id`/`TASTE`, 25일, 라벨 버전) |
| `functions/collect/handler.py` | 로그인 작업이면 고른 채널의 이 도시 영상을 최대 2개 앞에(분석된 것 먼저, 없으면 새로 분석) |
| 테스트 | `tests/unit/rules/test_taste.py`, `tests/unit/clients/test_youtube_taste.py`, `test_taste_labeler.py`, `tests/integration/test_api_me.py`, `test_collect.py` 뒷부분 |

확인: `make test`, `make lint`.

## 3. 지켜야 할 원칙 (테스트가 막는 것)

- 사용자는 JWT `sub`로만 정한다(`google:<sub>`). 본문의 `userId`는 400.
- 유튜브 액세스 토큰, 채널 이름, 영상 제목, 좋아요 영상 ID는 **어느 테이블에도 저장하지 않는다**(`test_import_returns_candidates_and_stores_only_ids`).
- Bedrock 라벨은 제안이다. 근거 문장이 채널 글에 그대로 없으면 UNKNOWN. 저장은 사용자 확인 뒤.
- 개인 영상은 일반 영상 자리를 **대신한다**(요청당 최대 5개 유지). 이미 분석된 개인 영상을 먼저 쓰고, 없으면 새로 분석한다(2026-11-25 개정).
- 채널 라벨은 채널 단위 캐시. 같은 채널은 사용자가 달라도 Bedrock 1회.
- 구독자 수·좋아요 수는 점수에 쓰지 않는다.

## 4. 남은 일 (순서대로)

1. ~~**`api_jobs`**~~ **완료(2026-11-25).** `POST /jobs`(요청 스타일이 비면 저장된 선호), `GET /jobs/{jobId}`(본인 작업만), `POST /jobs/{jobId}/rerank`(순위만 다시, 저장 안 함). 게스트와 공통인 작업 만들기·조회는 `functions/job_api.py`. 집계가 로그인 작업이면 참고 채널을 순위에 반영한다. 게스트 경로는 **체험 모드로 유지**한다(테스트 사용자 등록 없이 누구나 써 볼 수 있고, 개인화 전후 비교를 보여 줄 수 있어서).
2. **M8 로그인 배포:** API Gateway JWT Authorizer(issuer `https://accounts.google.com`, audience = OAuth 클라이언트 ID), `/me/*`·`/jobs` 경로, `api_me`·`api_jobs` Lambda. 결정 0007-2의 TODO(`iss` 형식) 확인.
3. **Google Cloud 설정:** OAuth 클라이언트(웹), 동의 화면 테스트 모드 + 테스트 사용자 등록, 연결 버튼에서만 `youtube.readonly` 요청.
4. **프론트:** 유튜브 연결 버튼 → `POST /me/youtube/import`(헤더 `X-Google-Access-Token`) → 후보 체크 화면 → `POST /me/youtube/confirm`. 연결 해제 버튼.
5. **공식 문서로 확인(TODO verify):** 각 호출 비용, `videos.list myRating=like`, 업로드 재생목록 ID(UC→UU 규칙).

## 5. 사람이 정할 것 (결정 0010)

- 3번: 사용자 구독 채널의 공개 제목·설명을 학교 게이트웨이로 보낸다는 안내 문구를 연결 화면에 넣을지.
- 4번: OAuth 동의 화면과 테스트 사용자 등록을 누가 할지.

## 6. 참고

- 라벨 프롬프트를 바꾸면 `shared/clients/taste.py`의 `LABEL_VERSION`을 올린다(채널 라벨 캐시가 다시 만들어진다).
- 개인 영상 상한은 `rules/taste.py`의 `MAX_PERSONAL_VIDEOS`, 업로드를 보는 채널 수는 `collect`의 `MAX_PERSONAL_CHANNELS`.
- AWS 백엔드 배포 진행 상황은 `docs/handoff-aws-backend.md`.

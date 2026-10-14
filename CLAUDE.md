# CLAUDE.md — tripvlog-map

이 파일은 Claude Code가 세션마다 가장 먼저 읽는 프로젝트 규칙이다. 상세 명세는 `docs/implementation-spec.md`, 기획 배경은 `docs/기획서.md`, 결정 기록은 `docs/decisions/`에 있다. 규칙이 충돌하면 이 파일 → implementation-spec → 기획서 순서로 따른다.

## 프로젝트 한 줄 요약

목적지(해외 도시)를 입력하면 한국어 여행 브이로그를 자동으로 골라 Gemini로 관찰하고 Bedrock으로 해석해, 여러 채널에서 확인된 장소 방문·평가·방문 시간대 근거를 Google 지도에 보여주는 서버리스 웹 서비스. 2인 팀 졸업 프로젝트(AWS Bedrock 활용 필수).

## 확정된 결정 (되돌리지 말 것)

1. **동선·일정 없음.** 기간 입력, 일자별 일정, 방문 순서, 경로를 만들지 않는다. 대신 영상 근거 기반 "방문 시간대 근거"를 보여준다.
2. **로그인은 선택.** 비로그인은 `/public/*` 경로, 로그인은 Cognito JWT가 걸린 `/jobs`, `/me/*` 경로. 한 경로에서 "인증 선택"을 하지 않는다.
3. **Google OAuth 토큰 미저장.** 유튜브 연결은 브라우저가 받은 짧은 수명 액세스 토큰으로 요청 중 1회 조회하고 버린다. refresh 토큰·KMS 보관 없음.
4. **Bedrock은 US 리전 하나**(기본 us-east-1)에 전체 스택을 둔다. 모델 ID는 하드코딩하지 말고 설정값으로 둔다.
5. **영상은 내려받지 않는다.** Gemini에는 공개 YouTube URL만 넘긴다.
6. **Places 응답은 Bedrock에 넘기지 않는다.** 지점 매칭은 일반 코드(규칙)로 한다.
7. **첫 버전 범위:** 해외 도시 1곳, 요청당 서로 다른 채널 영상 최대 5개, 식당·카페·관광지.

## 기술 스택

- 프론트: React + Vite + TypeScript, Tailwind CSS, TanStack Query, `@vis.gl/react-google-maps`
- 백엔드: Python 3.12 Lambda(컨테이너 이미지, ECR), Pydantic v2, boto3, google-genai
- 오케스트레이션: Step Functions Standard (Inline Map)
- 저장: DynamoDB 온디맨드 6개 테이블, S3(결과 JSON), SSM Parameter Store(서버 키)
- 인증: Cognito User Pool(Google IdP) + API Gateway HTTP API JWT Authorizer
- 인프라: AWS CDK (Python) / CI: GitHub Actions / 로컬: Docker Compose + DynamoDB Local
- 테스트: pytest, moto, Vitest

## 저장소 구조

```
frontend/                 React 앱
backend/functions/<name>/ Lambda 핸들러 (api_public, api_jobs, api_me, collect, observe, interpret, match, aggregate, cleanup)
backend/shared/           schemas/ (Pydantic), repos/ (DynamoDB·S3), clients/ (youtube, gemini, bedrock, places), rules/ (matching, aggregation, time_evidence, ranking)
backend/tests/            unit/, integration/, fixtures/
infra/                    CDK 앱 (stacks/)
experiments/              정답셋 라벨, 규칙 vs Bedrock 비교 스크립트, 결과
docs/                     기획서, implementation-spec, decisions/
```

## 코딩 규칙

- 모든 외부 입출력(API 요청·응답, AI 출력, DynamoDB 아이템)은 `backend/shared/schemas`의 Pydantic 모델로 검증한다. dict를 그대로 흘려보내지 않는다.
- 외부 API 호출은 `backend/shared/clients`에만 둔다. 핸들러는 clients·repos·rules를 조합만 한다.
- 비즈니스 규칙(매칭, 집계, 시간대, 순위)은 순수 함수로 `backend/shared/rules`에 두고 단위 테스트를 반드시 붙인다.
- AI가 결론을 내리게 하지 않는다. Gemini는 관찰만, Bedrock은 해석만, 확정·집계·순위는 규칙 코드가 한다.
- 근거가 없으면 `null` 또는 `UNKNOWN`으로 둔다. 추측으로 채우지 않는다. 이 원칙은 프롬프트와 코드 양쪽에 적용한다.
- 영상 재생 위치(`videoTimeRange`, 초)와 실제 방문 시각(`visitTimeEvidence.localClockTime`)을 섞지 않는다.
- 로그에 토큰, guestAccessToken 원문, Google Places 원문 응답, 좌표를 남기지 않는다.
- 요청 본문의 userId를 신뢰하지 않는다. 사용자는 JWT의 `sub`로만 결정한다.
- Step Functions 단계 사이에는 ID·상태·S3 키만 넘긴다(256 KiB 제한).
- 커밋은 Conventional Commits(`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `ci:`).

## 하지 말 것

- 일정·동선·경로·기간 입력 관련 코드나 UI를 만들지 않는다.
- 조회수·좋아요 수·구독자 수·업로드일을 장소 점수에 쓰지 않는다(검색 정렬에만 사용 가능).
- Google 응답의 이름·주소·카테고리를 DB에 저장하지 않는다(장소 ID와 25일 임시 좌표만).
- yt-dlp 등으로 영상을 내려받지 않는다.
- 쿠버네티스·젠킨스·EC2 상시 서버를 추가하지 않는다.
- 실제 유료 API(Gemini, Places, Bedrock)를 테스트에서 호출하지 않는다. fixture와 mock을 쓴다.

## 작업 방식

- 마일스톤 순서는 `docs/implementation-spec.md`의 "구현 순서"를 따른다. 한 번에 한 마일스톤만 진행하고, 완료 조건(테스트 통과)을 확인한 뒤 다음으로 간다.
- 명세에 없는 결정이 필요하면 임의로 정하지 말고 `docs/decisions/`에 제안 파일을 만들고 사람에게 묻는다.
- 모델 ID, 리전, 한도 값처럼 콘솔에서 확인해야 하는 값은 `infra/config.py`와 환경 변수로 빼고 TODO로 표시한다.
- 명령: `make test` (pytest + vitest), `make lint` (ruff, mypy, eslint, tsc), `make local` (docker compose up), `cdk synth`.

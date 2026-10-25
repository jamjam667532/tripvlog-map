"""환경별 설정값. 콘솔에서 확인해야 하는 값은 TODO(verify)로 표시한다.

Lambda에는 CDK가 이 값을 환경 변수로 넘긴다. 코드에 모델 ID를 하드코딩하지 않는다.
"""

REGION = "us-east-1"  # TODO(verify): 학교 계정에서 허용된 US 리전
# TODO(verify): Claude Haiku 4.5 모델 ID 또는 추론 프로파일(us. 접두사)
BEDROCK_INTERPRETER_MODEL_ID = "..."
BEDROCK_COMPARE_MODEL_ID = (
    "bedrock-gpt-5.6-luna"  # 학교 게이트웨이 별칭. M7 비교 실험에만 (결정 0007-1)
)
GEMINI_MODEL = "..."  # TODO(verify): 무료 티어에서 YouTube URL 입력을 지원하는 Flash 계열
# TODO(verify): LOW는 토큰을 줄이지만 간판·자막 인식이 떨어질 수 있다. M7에서 LOW/MEDIUM 비교
GEMINI_MEDIA_RESOLUTION = "MEDIA_RESOLUTION_LOW"
# TODO(verify): 해석 모델이 Converse 구조화 출력(outputConfig json_schema)을 지원하는지
BEDROCK_STRUCTURED_OUTPUT = True
ANALYSIS_VERSION = "v1-haiku45"  # 모델·프롬프트·스키마가 바뀌면 올린다
MAX_VIDEOS_PER_JOB = 5
SPARE_VIDEOS_PER_JOB = 3  # collect가 남겨 두는 예비 영상(서로 다른 채널). 저장만 하므로 비용 없음
MAX_REPLACEMENTS_PER_JOB = 1  # 실패 영상 대체 분석 상한 (결정 0002-5)
OBSERVE_RESERVED_CONCURRENCY = 1  # Gemini 전역 동시 호출 수. 첫 검증 후 조정
COORD_TTL_DAYS = 25
YOUTUBE_CACHE_TTL_DAYS = 25  # 30일 이내 갱신·삭제 운영안

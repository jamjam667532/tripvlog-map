"""환경별 설정값. 콘솔에서 확인해야 하는 값은 TODO(verify)로 표시한다.

Lambda에는 CDK가 이 값을 환경 변수로 넘긴다. 코드에 모델 ID를 하드코딩하지 않는다.
"""

REGION = "us-east-1"  # TODO(verify): 학교 계정에서 허용된 US 리전
# TODO(verify): Claude Haiku 4.5 모델 ID 또는 추론 프로파일(us. 접두사)
BEDROCK_INTERPRETER_MODEL_ID = "..."
BEDROCK_COMPARE_MODEL_ID = "..."  # TODO(verify): GPT 5.6 Luna 모델 ID
BEDROCK_STYLE_MODEL_ID = "..."  # TODO(verify): Amazon Nova Micro 모델 ID
GEMINI_MODEL = "..."  # TODO(verify): 무료 티어에서 YouTube URL 입력을 지원하는 Flash 계열
ANALYSIS_VERSION = "v1-haiku45"  # 모델·프롬프트·스키마가 바뀌면 올린다
MAX_VIDEOS_PER_JOB = 5
OBSERVE_RESERVED_CONCURRENCY = 1  # Gemini 전역 동시 호출 수. 첫 검증 후 조정
COORD_TTL_DAYS = 25
YOUTUBE_CACHE_TTL_DAYS = 25  # 30일 이내 갱신·삭제 운영안
STYLE_TAGGING_ENABLED = False  # 정책 확인 전에는 규칙 키워드 태깅만 사용 (spec §5.1)

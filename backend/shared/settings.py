"""Lambda 실행 설정. CDK가 infra/config.py 값을 환경 변수로 넘긴다.

기본값은 로컬·테스트용이다. 모델 ID처럼 콘솔에서 확인해야 하는 값은 기본값을 두지 않는다.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    return default if raw is None or raw == "" else int(raw)


def _opt(env: Mapping[str, str], name: str) -> str | None:
    return env.get(name) or None


@dataclass(frozen=True)
class Settings:
    jobs_table: str = "Jobs"
    users_table: str = "Users"
    youtube_cache_table: str = "YoutubeCache"
    video_analysis_table: str = "VideoAnalysis"
    places_table: str = "Places"
    coord_cache_table: str = "CoordCache"
    bucket: str = "tripvlog-local"
    dynamodb_endpoint: str | None = None  # DynamoDB Local (make local)

    analysis_version: str = "v1-haiku45"
    max_videos_per_job: int = 5
    spare_videos_per_job: int = 3
    max_replacements_per_job: int = 1
    coord_ttl_days: int = 25
    youtube_cache_ttl_days: int = 25
    lease_sec: int = 15 * 60  # spec §4.2 선점 15분
    max_claim_waits: int = 20  # 30초 x 20 = 10분 대기 후 실패
    # TODO(verify): YouTube 일일 할당량(10,000 units) 안에서 검색 1회 = 100 units
    daily_search_limit: int = 90

    state_machine_arn: str | None = None
    bedrock_region: str | None = None
    bedrock_interpreter_model_id: str | None = None
    bedrock_structured_output: bool = True
    gemini_model: str | None = None
    gemini_media_resolution: str = "MEDIA_RESOLUTION_LOW"
    # SSM Parameter Store 이름 (값이 아니라 이름)
    gemini_key_param: str = "/tripvlog/gemini-api-key"
    youtube_key_param: str = "/tripvlog/youtube-api-key"
    places_key_param: str = "/tripvlog/places-api-key"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        e = os.environ if env is None else env
        d = cls()
        return cls(
            jobs_table=e.get("JOBS_TABLE", d.jobs_table),
            users_table=e.get("USERS_TABLE", d.users_table),
            youtube_cache_table=e.get("YOUTUBE_CACHE_TABLE", d.youtube_cache_table),
            video_analysis_table=e.get("VIDEO_ANALYSIS_TABLE", d.video_analysis_table),
            places_table=e.get("PLACES_TABLE", d.places_table),
            coord_cache_table=e.get("COORD_CACHE_TABLE", d.coord_cache_table),
            bucket=e.get("DATA_BUCKET", d.bucket),
            dynamodb_endpoint=_opt(e, "DYNAMODB_ENDPOINT"),
            analysis_version=e.get("ANALYSIS_VERSION", d.analysis_version),
            max_videos_per_job=_int(e, "MAX_VIDEOS_PER_JOB", d.max_videos_per_job),
            spare_videos_per_job=_int(e, "SPARE_VIDEOS_PER_JOB", d.spare_videos_per_job),
            max_replacements_per_job=_int(
                e, "MAX_REPLACEMENTS_PER_JOB", d.max_replacements_per_job
            ),
            coord_ttl_days=_int(e, "COORD_TTL_DAYS", d.coord_ttl_days),
            youtube_cache_ttl_days=_int(e, "YOUTUBE_CACHE_TTL_DAYS", d.youtube_cache_ttl_days),
            lease_sec=_int(e, "LEASE_SEC", d.lease_sec),
            max_claim_waits=_int(e, "MAX_CLAIM_WAITS", d.max_claim_waits),
            daily_search_limit=_int(e, "DAILY_SEARCH_LIMIT", d.daily_search_limit),
            state_machine_arn=_opt(e, "STATE_MACHINE_ARN"),
            bedrock_region=_opt(e, "BEDROCK_REGION"),
            bedrock_interpreter_model_id=_opt(e, "BEDROCK_INTERPRETER_MODEL_ID"),
            bedrock_structured_output=e.get("BEDROCK_STRUCTURED_OUTPUT", "true").lower() == "true",
            gemini_model=_opt(e, "GEMINI_MODEL"),
            gemini_media_resolution=e.get("GEMINI_MEDIA_RESOLUTION", d.gemini_media_resolution),
            gemini_key_param=e.get("GEMINI_KEY_PARAM", d.gemini_key_param),
            youtube_key_param=e.get("YOUTUBE_KEY_PARAM", d.youtube_key_param),
            places_key_param=e.get("PLACES_KEY_PARAM", d.places_key_param),
        )


def require(value: str | None, name: str) -> str:
    """콘솔에서 확인해야 하는 값이 비어 있으면 실제 클라이언트를 만들지 않는다."""
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value

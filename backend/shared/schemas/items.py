"""DynamoDB 아이템 (spec §4). 모든 아이템은 이 모델로 쓰고 읽는다.

Google Places 응답의 이름·주소·카테고리는 어떤 아이템에도 두지 않는다(장소 ID와 임시 좌표만).
"""

from typing import Annotated, Literal

from pydantic import UUID4, AwareDatetime, Field, field_validator, model_validator

from shared.schemas.api import JobStatus, Preferences, Progress, VideoState
from shared.schemas.base import CamelModel
from shared.schemas.common import (
    Category,
    ChannelId,
    EpochSeconds,
    MatchStatus,
    NonEmptyStr,
    Ratings,
    Style,
    TimeEvidence,
    VideoId,
    VideoTimeRange,
    VisitStatus,
    truncate_evidence,
)

NonNegative = Annotated[int, Field(ge=0)]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


# ---------- Jobs ----------


class JobRequestSpec(Preferences):
    destination: NonEmptyStr


class VideoRef(CamelModel):
    video_id: VideoId
    channel_id: ChannelId
    analysis_version: NonEmptyStr
    state: VideoState = "PENDING"
    error: str | None = None
    replaces: VideoId | None = None  # 결정 0002-5: 실패 영상 대신 분석한 대체 영상이면 원래 videoId


class SpareVideo(CamelModel):
    """collect가 남겨 둔 예비 영상. 분석 실패 시 대체 후보(결정 0002-5)."""

    video_id: VideoId
    channel_id: ChannelId
    duration_sec: NonNegative  # 새로 분석할 때 짧은 영상부터(Gemini 비용은 길이에 비례)


class JobMetrics(CamelModel):
    elapsed_sec: NonNegative = 0
    gemini_tokens: NonNegative = 0
    bedrock_input_tokens: NonNegative = 0
    bedrock_output_tokens: NonNegative = 0
    places_calls: NonNegative = 0
    youtube_units: NonNegative = 0


class JobItem(CamelModel):
    job_id: UUID4
    request_id: UUID4
    user_id: NonEmptyStr | None = None
    guest_access_hash: Sha256Hex | None = None
    status: JobStatus
    request: JobRequestSpec
    video_refs: list[VideoRef] = Field(default_factory=list)
    spare_videos: list[SpareVideo] = Field(default_factory=list)
    progress: Progress = Field(default_factory=Progress)
    execution_arn: str | None = None
    result_s3_key: str | None = None
    metrics: JobMetrics = Field(default_factory=JobMetrics)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _single_owner(self) -> "JobItem":
        # 로그인 작업은 userId, 비로그인 작업은 guestAccessHash. 둘 중 정확히 하나.
        if (self.user_id is None) == (self.guest_access_hash is None):
            raise ValueError("exactly one of userId or guestAccessHash is required")
        return self

    @model_validator(mode="after")
    def _distinct_channels(self) -> "JobItem":
        # 분석 영상과 예비 영상 모두 채널당 1개
        channels = [r.channel_id for r in self.video_refs] + [
            s.channel_id for s in self.spare_videos
        ]
        if len(set(channels)) != len(channels):
            raise ValueError("videoRefs and spareVideos must come from different channels")
        return self

    @model_validator(mode="after")
    def _replacement_targets_failed(self) -> "JobItem":
        failed = {r.video_id for r in self.video_refs if r.state == "FAILED"}
        for ref in self.video_refs:
            if ref.replaces is not None and ref.replaces not in failed:
                raise ValueError("replaces must point to a FAILED video in videoRefs")
        return self


# ---------- VideoAnalysis ----------


class AnalysisUsage(CamelModel):
    gemini_tokens: NonNegative = 0
    bedrock_input_tokens: NonNegative = 0
    bedrock_output_tokens: NonNegative = 0


class VideoAnalysisItem(CamelModel):
    video_id: VideoId
    analysis_version: NonEmptyStr
    status: Literal["ANALYZING", "DONE", "FAILED"]
    lock_owner: NonEmptyStr | None = None  # 선점한 jobId
    lease_until: EpochSeconds | None = None
    channel_id: ChannelId
    style_tag: Style | Literal["복합", "분류불가"] | None = None
    observation_s3_key: str | None = None
    interpretation_s3_key: str | None = None
    usage: AnalysisUsage = Field(default_factory=AnalysisUsage)
    analyzed_at: AwareDatetime | None = None
    last_checked_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _state_fields(self) -> "VideoAnalysisItem":
        if self.status == "ANALYZING" and (self.lock_owner is None or self.lease_until is None):
            raise ValueError("ANALYZING requires lockOwner and leaseUntil")
        if self.status == "DONE" and (
            self.observation_s3_key is None or self.interpretation_s3_key is None
        ):
            raise ValueError("DONE requires observationS3Key and interpretationS3Key")
        return self


# ---------- Places ----------


class PlaceEvidenceItem(CamelModel):
    """Places 근거 아이템. sk = EVID#{channelId}#{videoId}#{analysisVersion}#{startSec}."""

    place_id: NonEmptyStr
    sk: NonEmptyStr
    video_id: VideoId
    channel_id: ChannelId
    analysis_version: NonEmptyStr
    evidence_key: NonEmptyStr  # {placeId}#{analysisVersion}#{startSec}
    visit_status: VisitStatus
    match_status: MatchStatus
    video_time_range: VideoTimeRange
    clue_types: list[Literal["SPEECH", "SCREEN_TEXT", "SCENE"]] = Field(default_factory=list)
    ratings: Ratings = Field(default_factory=Ratings)
    evidence_text: Annotated[str, Field(max_length=200)]
    visit_time_evidence: list[TimeEvidence] = Field(default_factory=list)

    _truncate = field_validator("evidence_text", mode="before")(truncate_evidence)

    @staticmethod
    def make_sk(channel_id: str, video_id: str, analysis_version: str, start_sec: int) -> str:
        return f"EVID#{channel_id}#{video_id}#{analysis_version}#{start_sec}"

    @staticmethod
    def make_evidence_key(place_id: str, analysis_version: str, start_sec: int) -> str:
        return f"{place_id}#{analysis_version}#{start_sec}"

    @model_validator(mode="after")
    def _keys_consistent(self) -> "PlaceEvidenceItem":
        start = self.video_time_range.start_sec
        if self.sk != self.make_sk(self.channel_id, self.video_id, self.analysis_version, start):
            raise ValueError("sk does not match channelId/videoId/analysisVersion/startSec")
        if self.evidence_key != self.make_evidence_key(self.place_id, self.analysis_version, start):
            raise ValueError("evidenceKey does not match placeId/analysisVersion/startSec")
        return self


class PlaceItem(CamelModel):
    """장소 아이템. 이름은 영상에서 관찰한 표기만 둔다(Google 응답 필드 저장 금지)."""

    place_id: NonEmptyStr
    sk: Literal["PLACE"] = "PLACE"
    destination: NonEmptyStr
    extracted_name: NonEmptyStr
    aliases: list[NonEmptyStr] = Field(default_factory=list)
    category_from_video: Category


# ---------- CoordCache / YoutubeCache ----------


class CoordCacheItem(CamelModel):
    """Google 좌표 임시 보관(25일). 이름·주소는 두지 않는다."""

    place_id: NonEmptyStr
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
    expires_at: EpochSeconds


class YoutubeSearchCacheItem(CamelModel):
    """pk = SEARCH#{hash}, sk = RESULT. 저장 필드는 결정 0002-3."""

    pk: Annotated[str, Field(pattern=r"^SEARCH#[0-9a-f]{64}$")]
    sk: Literal["RESULT"] = "RESULT"
    video_ids: list[VideoId]
    expires_at: EpochSeconds


class YoutubeVideoCacheItem(CamelModel):
    """pk = VIDEO#{videoId}, sk = META. 저장 필드는 결정 0002-3.

    조회수 등 지표는 점수에 쓰지 않으므로 두지 않는다. 제목·설명란은 스타일 태깅용.
    """

    pk: Annotated[str, Field(pattern=r"^VIDEO#[A-Za-z0-9_-]{1,64}$")]
    sk: Literal["META"] = "META"
    channel_id: ChannelId
    title: str
    description: str = ""
    duration_sec: NonNegative
    privacy_status: Literal["public", "unlisted", "private"]
    published_at: AwareDatetime
    expires_at: EpochSeconds


# ---------- Users (2단계) ----------


class UserPreferences(Preferences):
    reference_channel_ids: list[ChannelId] = Field(default_factory=list)


class YoutubeLink(CamelModel):
    """유튜브 API에서 온 데이터. 연결 해제·만료 시 이 속성만 REMOVE."""

    linked: bool
    synced_at: AwareDatetime
    resync_due_at: AwareDatetime
    travel_channel_ids: list[ChannelId] = Field(default_factory=list)
    liked_travel_video_ids: list[VideoId] = Field(default_factory=list)
    style_profile_candidate: dict[Style, Annotated[float, Field(ge=0, le=1)]] = Field(
        default_factory=dict
    )


class UserItem(CamelModel):
    user_id: NonEmptyStr  # Cognito sub
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    youtube: YoutubeLink | None = None

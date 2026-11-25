"""[M8] 유튜브 구독·좋아요 취향 분석의 입출력 (결정 0010).

채널 이름·설명, 영상 제목은 분석하는 동안 메모리에서만 쓰고 DB에 저장하지 않는다.
"""

from typing import Annotated

from pydantic import AwareDatetime, Field

from shared.schemas.base import AIModel, CamelModel
from shared.schemas.common import ChannelId, Style, TravelLabel, VideoId
from shared.schemas.items import UserPreferences

MAX_LABEL_STYLES = 2


class ChannelInfo(CamelModel):
    """공개 채널 정보 (channels.list). 메모리 전용."""

    channel_id: ChannelId
    title: str = ""
    description: str = ""


class ChannelVideo(CamelModel):
    """좋아요한 영상 또는 채널 업로드 영상의 공개 정보. 메모리 전용."""

    video_id: VideoId
    channel_id: ChannelId
    title: str = ""
    description: str = ""


class ChannelTasteLabel(AIModel):
    """Bedrock이 채널 하나에 붙인 라벨. 근거(evidence)는 입력 제목·설명의 원문 일부여야 한다."""

    channel_id: ChannelId
    travel: TravelLabel
    styles: Annotated[list[Style], Field(max_length=MAX_LABEL_STYLES)] = Field(default_factory=list)
    evidence: str | None = None


class ChannelTasteLabels(AIModel):
    labels: list[ChannelTasteLabel]


class TasteChannelCandidate(CamelModel):
    """연결 화면에 보여 줄 채널 후보. 사용자가 고른 것만 저장한다."""

    channel_id: ChannelId
    title: str
    travel: TravelLabel
    styles: list[Style] = Field(default_factory=list)
    evidence: str | None = None
    applied: bool = False  # 자동 취향 프로필에 들어갔는가(결정 0010 개정)


class YoutubeImportResponse(CamelModel):
    """POST /me/youtube/import 응답."""

    channels: list[TasteChannelCandidate]
    style_profile: dict[Style, float]
    subscriptions_checked: int
    liked_checked: int


class MeResponse(CamelModel):
    """GET /me/preferences 등의 응답. 유튜브에서 온 것은 후보로 따로 보여 준다."""

    preferences: UserPreferences
    youtube_linked: bool = False
    synced_at: AwareDatetime | None = None
    resync_due_at: AwareDatetime | None = None
    travel_channel_ids: list[ChannelId] = Field(default_factory=list)
    style_profile_candidate: dict[Style, float] = Field(default_factory=dict)

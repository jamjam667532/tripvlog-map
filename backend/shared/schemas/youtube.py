"""YouTube Data API 응답 중 필요한 필드만 (spec §5.1). 조회수·좋아요 수·구독자 수는 받지 않는다."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from shared.schemas.common import ChannelId, VideoId


class VideoMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    video_id: VideoId
    channel_id: ChannelId
    title: str
    description: str
    duration_sec: int
    privacy_status: Literal["public", "unlisted", "private"]
    published_at: AwareDatetime
    embeddable: bool = True
    tags: list[str] = Field(default_factory=list)  # 올린 사람이 붙인 태그(결정 0011, 영상 임베딩용)

"""[1] YouTube Data API v3 (spec §5.1). search.list(100 units), videos.list(1 unit).

취향 분석(결정 0010)은 1 unit 호출만 쓴다: channels.list, playlistItems.list(채널 업로드),
그리고 사용자 액세스 토큰으로 subscriptions.list(mine), videos.list(myRating=like).
사용자 토큰은 요청 중에만 쓰고 저장·로그하지 않는다(확정 결정 3).
TODO(verify): 각 호출 비용, myRating=like 동작, 업로드 목록 ID(UC→UU) 규칙을 공식 문서로 확인.
"""

import re
import urllib.parse
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Protocol

from shared.clients.errors import ExternalApiError
from shared.clients.http import HttpRequest, Transport, request_json, urllib_transport
from shared.schemas.taste import ChannelInfo, ChannelVideo
from shared.schemas.youtube import VideoMeta

BASE_URL = "https://www.googleapis.com/youtube/v3"
SEARCH_UNITS = 100
VIDEOS_UNITS = 1
MAX_IDS_PER_VIDEOS_CALL = 50
LIST_UNITS = 1  # channels·playlistItems·subscriptions·videos(myRating) 1쪽
PAGE_SIZE = 50
MAX_SUBSCRIPTION_PAGES = 4  # 구독 최대 200개
MAX_LIKED_PAGES = 2  # 좋아요 최대 100개

SearchOrder = Literal["relevance", "date"]

_DURATION = re.compile(r"^P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$")


def parse_duration(value: str) -> int:
    """ISO 8601 기간(PT12M3S, P1DT2H, P0D) → 초."""
    m = _DURATION.match(value)
    if not m:
        raise ValueError(f"unsupported duration: {value!r}")
    d, h, mi, s = (int(m.group(k) or 0) for k in ("d", "h", "m", "s"))
    return ((d * 24 + h) * 60 + mi) * 60 + s


class YouTubeClient(Protocol):
    def search(
        self, query: str, *, order: SearchOrder, published_after: datetime, max_results: int = 25
    ) -> list[str]: ...

    def videos(self, video_ids: Sequence[str]) -> list[VideoMeta]: ...

    def channels(self, channel_ids: Sequence[str]) -> list[ChannelInfo]: ...

    def uploads(self, channel_id: str, max_results: int = PAGE_SIZE) -> list[ChannelVideo]: ...


class YouTubeUserClient(Protocol):
    """사용자 액세스 토큰으로 부르는 조회. 토큰은 만든 쪽이 요청이 끝나면 버린다."""

    def subscription_channel_ids(self) -> list[str]: ...

    def liked_videos(self) -> list[ChannelVideo]: ...


def uploads_playlist_id(channel_id: str) -> str | None:
    """채널 업로드 재생목록 ID. UC로 시작하는 채널 ID는 UU로 바꾼 값이다. TODO(verify)"""
    return "UU" + channel_id[2:] if channel_id.startswith("UC") and len(channel_id) > 2 else None


class YouTubeDataApi:
    def __init__(
        self, api_key: str, *, transport: Transport = urllib_transport, timeout: float = 10.0
    ) -> None:
        self._key = api_key
        self._transport = transport
        self._timeout = timeout
        self.units_used = 0  # Jobs.metrics.youtubeUnits

    def __repr__(self) -> str:
        return "YouTubeDataApi()"

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode({**params, "key": self._key})
        return request_json(
            self._transport,
            "youtube",
            HttpRequest("GET", f"{BASE_URL}/{path}?{query}"),
            self._timeout,
        )

    def search(
        self, query: str, *, order: SearchOrder, published_after: datetime, max_results: int = 25
    ) -> list[str]:
        data = self._get(
            "search",
            {
                "part": "id",
                "q": query,
                "type": "video",
                "order": order,
                "maxResults": max_results,
                "relevanceLanguage": "ko",
                "publishedAfter": published_after.isoformat().replace("+00:00", "Z"),
                "fields": "items/id/videoId",
            },
        )
        self.units_used += SEARCH_UNITS
        ids = [i.get("id", {}).get("videoId") for i in data.get("items", [])]
        return list(dict.fromkeys(v for v in ids if v))

    def videos(self, video_ids: Sequence[str]) -> list[VideoMeta]:
        metas: list[VideoMeta] = []
        unique = list(dict.fromkeys(video_ids))
        for i in range(0, len(unique), MAX_IDS_PER_VIDEOS_CALL):
            chunk = unique[i : i + MAX_IDS_PER_VIDEOS_CALL]
            data = self._get(
                "videos",
                {
                    "part": "snippet,contentDetails,status",
                    "id": ",".join(chunk),
                    "fields": (
                        "items(id,snippet(channelId,title,description,publishedAt),"
                        "contentDetails/duration,status(privacyStatus,embeddable))"
                    ),
                },
            )
            self.units_used += VIDEOS_UNITS
            metas.extend(_to_meta(item) for item in data.get("items", []))
        return metas

    def channels(self, channel_ids: Sequence[str]) -> list[ChannelInfo]:
        infos: list[ChannelInfo] = []
        unique = list(dict.fromkeys(channel_ids))
        for i in range(0, len(unique), PAGE_SIZE):
            data = self._get(
                "channels",
                {
                    "part": "snippet",
                    "id": ",".join(unique[i : i + PAGE_SIZE]),
                    "maxResults": PAGE_SIZE,
                    "fields": "items(id,snippet(title,description))",
                },
            )
            self.units_used += LIST_UNITS
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                if item.get("id"):
                    infos.append(
                        ChannelInfo(
                            channel_id=item["id"],
                            title=snippet.get("title", ""),
                            description=snippet.get("description", ""),
                        )
                    )
        return infos

    def uploads(self, channel_id: str, max_results: int = PAGE_SIZE) -> list[ChannelVideo]:
        playlist = uploads_playlist_id(channel_id)
        if playlist is None:
            return []
        data = self._get(
            "playlistItems",
            {
                "part": "snippet",
                "playlistId": playlist,
                "maxResults": min(max_results, PAGE_SIZE),
                "fields": "items/snippet(title,description,resourceId/videoId)",
            },
        )
        self.units_used += LIST_UNITS
        out: list[ChannelVideo] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId")
            if video_id:
                out.append(
                    ChannelVideo(
                        video_id=video_id,
                        channel_id=channel_id,
                        title=snippet.get("title", ""),
                        description=snippet.get("description", ""),
                    )
                )
        return out


class YouTubeUserApi:
    """사용자 액세스 토큰(youtube.readonly)으로 내 구독·좋아요를 읽는다. 토큰은 저장하지 않는다."""

    def __init__(
        self, access_token: str, *, transport: Transport = urllib_transport, timeout: float = 10.0
    ) -> None:
        self._token = access_token
        self._transport = transport
        self._timeout = timeout
        self.units_used = 0

    def __repr__(self) -> str:
        return "YouTubeUserApi()"  # 토큰을 드러내지 않는다

    def _pages(self, path: str, params: dict[str, Any], max_pages: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(max_pages):
            query = {**params, "maxResults": PAGE_SIZE, **({"pageToken": token} if token else {})}
            data = request_json(
                self._transport,
                "youtube",
                HttpRequest(
                    "GET",
                    f"{BASE_URL}/{path}?{urllib.parse.urlencode(query)}",
                    {"Authorization": f"Bearer {self._token}"},
                ),
                self._timeout,
            )
            self.units_used += LIST_UNITS
            items.extend(data.get("items", []))
            token = data.get("nextPageToken")
            if not token:
                break
        return items

    def subscription_channel_ids(self) -> list[str]:
        items = self._pages(
            "subscriptions",
            {
                "part": "snippet",
                "mine": "true",
                "fields": "nextPageToken,items/snippet/resourceId/channelId",
            },
            MAX_SUBSCRIPTION_PAGES,
        )
        ids = (i.get("snippet", {}).get("resourceId", {}).get("channelId") for i in items)
        return list(dict.fromkeys(c for c in ids if c))

    def liked_videos(self) -> list[ChannelVideo]:
        items = self._pages(
            "videos",
            {
                "part": "snippet",
                "myRating": "like",
                "fields": "nextPageToken,items(id,snippet(channelId,title,description))",
            },
            MAX_LIKED_PAGES,
        )
        out: list[ChannelVideo] = []
        for item in items:
            snippet = item.get("snippet", {})
            if item.get("id") and snippet.get("channelId"):
                out.append(
                    ChannelVideo(
                        video_id=item["id"],
                        channel_id=snippet["channelId"],
                        title=snippet.get("title", ""),
                        description=snippet.get("description", ""),
                    )
                )
        return out


def _to_meta(item: dict[str, Any]) -> VideoMeta:
    try:
        snippet, status = item["snippet"], item["status"]
        return VideoMeta(
            video_id=item["id"],
            channel_id=snippet["channelId"],
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            duration_sec=parse_duration(item["contentDetails"]["duration"]),
            privacy_status=status["privacyStatus"],
            published_at=snippet["publishedAt"],
            embeddable=status.get("embeddable", True),
        )
    except (KeyError, ValueError) as e:
        raise ExternalApiError(
            "youtube", 200, f"unexpected video item: {type(e).__name__}"
        ) from None

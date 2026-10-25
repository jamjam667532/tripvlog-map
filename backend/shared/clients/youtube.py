"""[1] YouTube Data API v3 (spec §5.1). search.list(100 units), videos.list(1 unit)."""

import re
import urllib.parse
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, Protocol

from shared.clients.errors import ExternalApiError
from shared.clients.http import HttpRequest, Transport, request_json, urllib_transport
from shared.schemas.youtube import VideoMeta

BASE_URL = "https://www.googleapis.com/youtube/v3"
SEARCH_UNITS = 100
VIDEOS_UNITS = 1
MAX_IDS_PER_VIDEOS_CALL = 50

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

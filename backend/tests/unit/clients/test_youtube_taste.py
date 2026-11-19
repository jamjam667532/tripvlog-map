"""[M8] YouTube 취향 조회 (결정 0010). 실제 YouTube는 부르지 않는다."""

import urllib.parse
from typing import Any

import pytest

from shared.clients.errors import ExternalApiError
from shared.clients.http import HttpRequest
from shared.clients.youtube import (
    MAX_SUBSCRIPTION_PAGES,
    YouTubeDataApi,
    YouTubeUserApi,
    uploads_playlist_id,
)
from tests.unit.clients.transport import RecordingTransport


def _query(req: HttpRequest) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(req.url).query))


def test_channels_and_uploads_cost_one_unit_each() -> None:
    def respond(req: HttpRequest) -> tuple[int, Any]:
        if "/channels?" in req.url:
            return 200, {"items": [{"id": "UCa", "snippet": {"title": "여행", "description": "d"}}]}
        return 200, {
            "items": [
                {"snippet": {"title": "오사카", "description": "", "resourceId": {"videoId": "v1"}}}
            ]
        }

    t = RecordingTransport(respond)
    yt = YouTubeDataApi("key", transport=t)
    assert [c.channel_id for c in yt.channels(["UCa", "UCa"])] == ["UCa"]
    ups = yt.uploads("UCa")
    assert [(u.video_id, u.channel_id) for u in ups] == [("v1", "UCa")]
    assert _query(t.requests[1])["playlistId"] == "UUa"
    assert yt.units_used == 2


def test_uploads_of_unusual_channel_id_is_empty_without_a_call() -> None:
    t = RecordingTransport(lambda req: (200, {}))
    assert uploads_playlist_id("HCabc") is None
    assert YouTubeDataApi("key", transport=t).uploads("HCabc") == []
    assert t.requests == []


def test_user_api_sends_token_as_bearer_and_follows_pages() -> None:
    pages = iter(
        [
            {"items": [{"snippet": {"resourceId": {"channelId": "c1"}}}], "nextPageToken": "p2"},
            {"items": [{"snippet": {"resourceId": {"channelId": "c2"}}}, {"snippet": {}}]},
        ]
    )
    t = RecordingTransport(lambda req: (200, next(pages)))
    api = YouTubeUserApi("user-token", transport=t)
    assert api.subscription_channel_ids() == ["c1", "c2"]
    assert all(r.headers["Authorization"] == "Bearer user-token" for r in t.requests)
    assert all("user-token" not in r.url for r in t.requests)  # 토큰은 주소에 넣지 않는다
    assert _query(t.requests[0])["mine"] == "true"
    assert _query(t.requests[1])["pageToken"] == "p2"
    assert api.units_used == 2
    assert "user-token" not in repr(api)


def test_subscription_pages_are_capped() -> None:
    t = RecordingTransport(lambda req: (200, {"items": [], "nextPageToken": "more"}))
    YouTubeUserApi("t", transport=t).subscription_channel_ids()
    assert len(t.requests) == MAX_SUBSCRIPTION_PAGES


def test_liked_videos_use_my_rating_like() -> None:
    body = {"items": [{"id": "v1", "snippet": {"channelId": "c1", "title": "오사카 맛집"}}]}
    t = RecordingTransport(lambda req: (200, body))
    liked = YouTubeUserApi("t", transport=t).liked_videos()
    assert [(v.video_id, v.channel_id, v.title) for v in liked] == [("v1", "c1", "오사카 맛집")]
    assert _query(t.requests[0])["myRating"] == "like"


def test_rejected_token_raises_with_status_only() -> None:
    t = RecordingTransport(lambda req: (401, {"error": {"message": "secret-ish body"}}))
    with pytest.raises(ExternalApiError) as e:
        YouTubeUserApi("t", transport=t).liked_videos()
    assert e.value.status == 401
    assert "secret-ish" not in str(e.value)

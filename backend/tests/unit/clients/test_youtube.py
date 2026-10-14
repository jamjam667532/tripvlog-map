import urllib.parse
from datetime import UTC, datetime

import pytest

from shared.clients.errors import ExternalApiError
from shared.clients.http import HttpRequest
from shared.clients.youtube import YouTubeDataApi, parse_duration

from .transport import RecordingTransport

KEY = "test-youtube-key"
SINCE = datetime(2024, 10, 15, tzinfo=UTC)


def _params(req: HttpRequest) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(req.url).query))


def _video(vid: str, duration: str = "PT12M3S", privacy: str = "public") -> dict[str, object]:
    return {
        "id": vid,
        "snippet": {
            "channelId": f"ch_{vid}",
            "title": "오사카 브이로그",
            "description": "",
            "publishedAt": "2026-05-01T09:00:00Z",
        },
        "contentDetails": {"duration": duration},
        "status": {"privacyStatus": privacy, "embeddable": True},
    }


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("PT12M3S", 723), ("PT1H", 3600), ("P1DT2H3M4S", 93784), ("P0D", 0), ("PT45S", 45)],
)
def test_parse_duration(value: str, seconds: int) -> None:
    assert parse_duration(value) == seconds


def test_search_returns_unique_ids_and_counts_units() -> None:
    t = RecordingTransport(
        lambda r: (200, {"items": [{"id": {"videoId": "a"}}, {"id": {"videoId": "a"}}, {"id": {}}]})
    )
    api = YouTubeDataApi(KEY, transport=t)
    assert api.search("오사카 브이로그", order="date", published_after=SINCE) == ["a"]
    p = _params(t.requests[0])
    assert p["q"] == "오사카 브이로그"
    assert (p["order"], p["type"], p["relevanceLanguage"]) == ("date", "video", "ko")
    assert p["publishedAfter"] == "2024-10-15T00:00:00Z"
    assert api.units_used == 100


def test_videos_never_requests_popularity_metrics() -> None:
    t = RecordingTransport(lambda r: (200, {"items": [_video("a")]}))
    YouTubeDataApi(KEY, transport=t).videos(["a"])
    p = _params(t.requests[0])
    assert "statistics" not in p["part"]
    assert not any(w in p["fields"] for w in ("viewCount", "likeCount", "statistics"))


def test_videos_parses_meta_and_chunks_by_50() -> None:
    ids = [f"v{i}" for i in range(60)]
    t = RecordingTransport(
        lambda r: (200, {"items": [_video(v) for v in _params(r)["id"].split(",")]})
    )
    api = YouTubeDataApi(KEY, transport=t)
    metas = api.videos([*ids, "v0"])
    assert len(t.requests) == 2
    assert len(metas) == 60
    assert metas[0].duration_sec == 723
    assert metas[0].channel_id == "ch_v0"
    assert api.units_used == 2


def test_error_does_not_leak_key() -> None:
    t = RecordingTransport(lambda r: (403, {"error": {"message": f"bad key {KEY}"}}))
    with pytest.raises(ExternalApiError) as e:
        YouTubeDataApi(KEY, transport=t).search("x", order="relevance", published_after=SINCE)
    assert e.value.status == 403
    assert KEY not in str(e.value)
    assert KEY not in repr(YouTubeDataApi(KEY, transport=t))


def test_malformed_item_is_external_error() -> None:
    t = RecordingTransport(lambda r: (200, {"items": [{"id": "a", "snippet": {}}]}))
    with pytest.raises(ExternalApiError):
        YouTubeDataApi(KEY, transport=t).videos(["a"])

import pytest

from shared.clients.errors import ExternalApiError
from shared.clients.places import MATCH_FIELD_MASK, PlacesTextSearch
from shared.schemas.places import GeoPoint

from .transport import RecordingTransport

KEY = "test-places-key"
OSAKA = GeoPoint(lat=34.69, lng=135.50)


def _place(pid: str, name: str) -> dict[str, object]:
    return {
        "id": pid,
        "displayName": {"text": name, "languageCode": "ko"},
        "formattedAddress": "일본 오사카부 오사카시 주오구 도톤보리 1-4",
        "location": {"latitude": 34.6687, "longitude": 135.5013},
    }


def test_request_uses_minimal_field_mask_language_and_bias() -> None:
    t = RecordingTransport(lambda r: (200, {"places": [_place("A", "이치란 도톤보리점")]}))
    hits = PlacesTextSearch(KEY, transport=t).search_candidate(["一蘭 道頓堀店"], bias=OSAKA)
    req = t.requests[0]
    assert req.headers["X-Goog-FieldMask"] == MATCH_FIELD_MASK
    assert req.headers["X-Goog-Api-Key"] == KEY
    assert KEY not in req.url
    body = t.body()
    assert body["textQuery"] == "一蘭 道頓堀店"
    assert body["languageCode"] == "ko"
    assert body["locationBias"]["circle"]["center"] == {"latitude": 34.69, "longitude": 135.5}
    assert [(h.place_id, h.name) for h in hits] == [("A", "이치란 도톤보리점")]


def test_field_mask_has_no_extra_google_content() -> None:
    fields = set(MATCH_FIELD_MASK.split(","))
    assert fields == {
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
    }


def test_stops_after_first_query_with_results() -> None:
    t = RecordingTransport(lambda r: (200, {"places": [_place("A", "이치란")]}))
    api = PlacesTextSearch(KEY, transport=t)
    api.search_candidate(["q1", "q2", "q3"], bias=None)
    assert api.calls == 1


def test_call_budget_is_two_per_candidate() -> None:
    t = RecordingTransport(lambda r: (200, {}))
    api = PlacesTextSearch(KEY, transport=t)
    assert api.search_candidate(["q1", "q2", "q3"], bias=None) == []
    assert [t.body(i)["textQuery"] for i in range(len(t.requests))] == ["q1", "q2"]
    assert "locationBias" not in t.body()


def test_locate_city() -> None:
    t = RecordingTransport(lambda r: (200, {"places": [_place("OSAKA", "오사카")]}))
    api = PlacesTextSearch(KEY, transport=t)
    assert api.locate("오사카") == GeoPoint(lat=34.6687, lng=135.5013)
    assert t.requests[0].headers["X-Goog-FieldMask"] == "places.id,places.location"


def test_http_error_and_bad_item() -> None:
    with pytest.raises(ExternalApiError) as e:
        PlacesTextSearch(KEY, transport=RecordingTransport(lambda r: (429, {}))).locate("x")
    assert e.value.status == 429
    bad = RecordingTransport(lambda r: (200, {"places": [{"id": "A"}]}))
    with pytest.raises(ExternalApiError):
        PlacesTextSearch(KEY, transport=bad).search_candidate(["q"], bias=None)


def test_transport_failure_is_external_error() -> None:
    def boom(req: object, timeout: float) -> object:
        raise TimeoutError

    with pytest.raises(ExternalApiError) as e:
        PlacesTextSearch(KEY, transport=boom).locate("x")  # type: ignore[arg-type]
    assert e.value.status is None

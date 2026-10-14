"""Google Places API (New) Text Search (spec §5.4).

- FieldMask로 매칭에 필요한 최소 필드만 요청한다.
- 응답은 메모리에서만 쓰고 로그·S3·DynamoDB에 남기지 않는다.
- 후보당 호출 예산은 최대 2회.
"""

import json
from collections.abc import Sequence
from typing import Any, Protocol

from shared.clients.errors import ExternalApiError
from shared.clients.http import HttpRequest, Transport, request_json, urllib_transport
from shared.schemas.places import GeoPoint, PlaceHit

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
MATCH_FIELD_MASK = "places.id,places.displayName,places.formattedAddress,places.location"
LOCATE_FIELD_MASK = "places.id,places.location"
MAX_CALLS_PER_CANDIDATE = 2
CITY_BIAS_RADIUS_M = 20_000.0  # Places API 상한 50 km
MAX_RESULTS = 5


class PlacesClient(Protocol):
    def locate(self, text: str) -> GeoPoint | None: ...

    def search_candidate(
        self, queries: Sequence[str], *, bias: GeoPoint | None
    ) -> list[PlaceHit]: ...


class PlacesTextSearch:
    def __init__(
        self,
        api_key: str,
        *,
        language: str = "ko",
        transport: Transport = urllib_transport,
        timeout: float = 10.0,
    ) -> None:
        self._key = api_key
        self._language = language
        self._transport = transport
        self._timeout = timeout
        self.calls = 0  # Jobs.metrics.placesCalls

    def __repr__(self) -> str:
        return "PlacesTextSearch()"

    def _search(
        self, text: str, field_mask: str, bias: GeoPoint | None, max_results: int
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "textQuery": text,
            "languageCode": self._language,
            "maxResultCount": max_results,
        }
        if bias is not None:
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": bias.lat, "longitude": bias.lng},
                    "radius": CITY_BIAS_RADIUS_M,
                }
            }
        req = HttpRequest(
            "POST",
            SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._key,
                "X-Goog-FieldMask": field_mask,
            },
            body=json.dumps(body).encode(),
        )
        self.calls += 1
        places = request_json(self._transport, "places", req, self._timeout).get("places", [])
        return places if isinstance(places, list) else []

    def locate(self, text: str) -> GeoPoint | None:
        """도시 이름 → 위치 편향 중심. 작업당 1회."""
        places = self._search(text, LOCATE_FIELD_MASK, None, 1)
        return _point(places[0]) if places else None

    def search_candidate(self, queries: Sequence[str], *, bias: GeoPoint | None) -> list[PlaceHit]:
        """검색어를 순서대로 최대 2회 호출. 결과가 나오면 멈춘다."""
        hits: list[PlaceHit] = []
        for query in list(queries)[:MAX_CALLS_PER_CANDIDATE]:
            hits = [_hit(p) for p in self._search(query, MATCH_FIELD_MASK, bias, MAX_RESULTS)]
            if hits:
                break
        return hits


def _point(place: dict[str, Any]) -> GeoPoint:
    try:
        loc = place["location"]
        return GeoPoint(lat=loc["latitude"], lng=loc["longitude"])
    except (KeyError, ValueError):
        raise ExternalApiError("places", 200, "place without location") from None


def _hit(place: dict[str, Any]) -> PlaceHit:
    try:
        return PlaceHit(
            place_id=place["id"],
            name=place.get("displayName", {}).get("text", ""),
            address=place.get("formattedAddress", ""),
            location=_point(place),
        )
    except (KeyError, ValueError):
        raise ExternalApiError("places", 200, "unexpected place item") from None

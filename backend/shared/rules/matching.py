"""장소 후보와 Places 검색 결과의 지점 매칭 (spec §5.4). Bedrock에 넘기지 않고 규칙으로 정한다.

1. 이름 유사도(정규화 후 문자열 유사도 + 별칭) >= 임계값
2. branch_hint가 있으면 그 단어가 모두 결과 이름·주소에 들어 있어야 한다
3. 위치 단서가 있을 때만 거리 조건
4. 남은 결과가 1곳이면 CONFIRMED, 0곳이면 버림, 2곳 이상이면 UNCONFIRMED(후보 보존)
"""

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from shared.schemas.places import GeoPoint, PlaceHit

# TODO(tune): experiments/의 dev 라벨로 조정한다
NAME_SIMILARITY_THRESHOLD = 0.8
DEFAULT_NEAR_RADIUS_M = 500.0

_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize(text: str) -> str:
    """NFKC(전각·반각 통일) → 소문자 → 공백·기호 제거."""
    return _NON_WORD.sub("", unicodedata.normalize("NFKC", text).casefold())


def name_similarity(names: Iterable[str], hit_name: str) -> float:
    """후보의 여러 표기(별칭 포함) 중 가장 높은 유사도. 결과 이름에 통째로 들어 있으면 1.0."""
    target = normalize(hit_name)
    best = 0.0
    for name in names:
        n = normalize(name)
        if not n or not target:
            continue
        if n in target:
            return 1.0
        best = max(best, SequenceMatcher(None, n, target).ratio())
    return best


def branch_matches(branch_hint: str, hit: PlaceHit) -> bool:
    haystack = normalize(hit.name) + normalize(hit.address)
    tokens = [normalize(t) for t in branch_hint.split()]
    return all(t in haystack for t in tokens if t)


def distance_m(a: GeoPoint, b: GeoPoint) -> float:
    """하버사인 거리(미터)."""
    r = 6_371_000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@dataclass(frozen=True)
class MatchOutcome:
    status: Literal["CONFIRMED", "UNCONFIRMED", "DISCARDED"]
    place_ids: tuple[str, ...]  # CONFIRMED면 1개, UNCONFIRMED면 남은 후보 전부

    @property
    def place_id(self) -> str | None:
        return self.place_ids[0] if self.status == "CONFIRMED" else None


def match_candidate(
    names: Sequence[str],
    branch_hint: str | None,
    hits: Sequence[PlaceHit],
    *,
    near: GeoPoint | None = None,
    near_radius_m: float = DEFAULT_NEAR_RADIUS_M,
    threshold: float = NAME_SIMILARITY_THRESHOLD,
) -> MatchOutcome:
    # 여러 검색어 결과에 같은 장소가 겹쳐 올 수 있다
    unique = list({h.place_id: h for h in hits}.values())

    remaining = [h for h in unique if name_similarity(names, h.name) >= threshold]
    if branch_hint and branch_hint.strip():
        remaining = [h for h in remaining if branch_matches(branch_hint, h)]
    if near is not None:
        remaining = [h for h in remaining if distance_m(near, h.location) <= near_radius_m]

    ids = tuple(sorted(h.place_id for h in remaining))
    if len(ids) == 1:
        return MatchOutcome("CONFIRMED", ids)
    if not ids:
        return MatchOutcome("DISCARDED", ())
    return MatchOutcome("UNCONFIRMED", ids)

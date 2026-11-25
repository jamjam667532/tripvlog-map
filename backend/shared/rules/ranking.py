"""[4] 장소 순위 (spec §5.5). 조회수·좋아요 수·구독자 수 등 API 지표는 입력으로 받지 않는다.

점수 = 방문 채널 수
     + 명시적 긍정(overall POSITIVE) 채널 수 x POSITIVE_WEIGHT
     + 선호 스타일 일치 x STYLE_WEIGHT
     + 참고 채널 방문 수 x REFERENCE_WEIGHT
     + 취향 스타일 비율과 겹치는 몫 x TASTE_WEIGHT (로그인 작업, 결정 0010 개정)
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from shared.rules.aggregation import PlaceAggregate
from shared.schemas.common import Category, Style

# TODO(tune): experiments/의 dev 라벨로 조정한다
POSITIVE_WEIGHT = 0.5
STYLE_WEIGHT = 1.0
REFERENCE_WEIGHT = 1.0
TASTE_WEIGHT = 1.0

# 결정 0003-5: 스타일 → 영상에서 본 장소 분류. 가성비는 가격 긍정, 쇼핑은 아직 대응 분류 없음
STYLE_CATEGORIES: Mapping[Style, Category] = {
    "맛집": "RESTAURANT",
    "카페·포토스팟": "CAFE",
    "관광·역사": "ATTRACTION",
}


@dataclass(frozen=True)
class Ranked:
    place_id: str
    rank: int
    score: float


def matched_styles(agg: PlaceAggregate, category: Category | None) -> set[Style]:
    """이 장소가 해당하는 스타일. 분류(식당·카페·관광지)와 가격 긍정(가성비)으로 정한다."""
    found: set[Style] = {s for s, c in STYLE_CATEGORIES.items() if c == category}
    if agg.ratings["price"].positive > 0:
        found.add("가성비")
    return found


def style_match(agg: PlaceAggregate, category: Category | None, styles: Collection[Style]) -> bool:
    return bool(matched_styles(agg, category) & set(styles))


def score(
    agg: PlaceAggregate,
    *,
    category: Category | None,
    styles: Collection[Style] = (),
    reference_channel_ids: Collection[str] = (),
    style_weights: Mapping[Style, float] | None = None,
) -> float:
    s = float(agg.channels_visited)
    s += POSITIVE_WEIGHT * agg.overall.positive
    if style_match(agg, category, styles):
        s += STYLE_WEIGHT
    s += REFERENCE_WEIGHT * len(agg.visited_channel_ids & set(reference_channel_ids))
    if style_weights:
        s += TASTE_WEIGHT * sum(style_weights.get(x, 0.0) for x in matched_styles(agg, category))
    return s


def rank_places(
    aggregates: Sequence[PlaceAggregate],
    *,
    categories: Mapping[str, Category],
    styles: Collection[Style] = (),
    reference_channel_ids: Collection[str] = (),
    style_weights: Mapping[Style, float] | None = None,
) -> list[Ranked]:
    """방문 채널이 없는(언급만 된) 장소는 순위에서 뺀다. 동점은 방문 채널 수, placeId 순."""
    scored = [
        (
            score(
                a,
                category=categories.get(a.place_id),
                styles=styles,
                reference_channel_ids=reference_channel_ids,
                style_weights=style_weights,
            ),
            a,
        )
        for a in aggregates
        if a.channels_visited > 0
    ]
    scored.sort(key=lambda x: (-x[0], -x[1].channels_visited, x[1].place_id))
    return [Ranked(a.place_id, i, s) for i, (s, a) in enumerate(scored, start=1)]

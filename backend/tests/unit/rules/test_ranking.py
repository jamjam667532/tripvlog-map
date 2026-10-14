import inspect
from collections.abc import Sequence

from shared.rules import ranking
from shared.rules.aggregation import PlaceAggregate, aggregate_places
from shared.rules.ranking import rank_places
from shared.schemas.common import Category
from shared.schemas.items import PlaceEvidenceItem

from .factories import evidence, ref

REFS = [ref(f"v{i}", f"ch{i}") for i in range(1, 6)]


def _aggs(evs: Sequence[PlaceEvidenceItem]) -> list[PlaceAggregate]:
    return aggregate_places(evs, REFS)


def test_more_visiting_channels_rank_higher() -> None:
    evs = [evidence("A", "ch1", "v1")] + [evidence("B", f"ch{i}", f"v{i}") for i in (1, 2, 3)]
    ranked = rank_places(_aggs(evs), categories={})
    assert [(r.place_id, r.rank) for r in ranked] == [("B", 1), ("A", 2)]


def test_explicit_positive_breaks_equal_visits() -> None:
    evs = [
        evidence("A", "ch1", "v1"),
        evidence("B", "ch2", "v2", ratings={"overall": "POSITIVE"}),
    ]
    assert [r.place_id for r in rank_places(_aggs(evs), categories={})] == ["B", "A"]


def test_preferred_style_and_reference_channel_boost() -> None:
    evs = [evidence("CAFE1", "ch1", "v1"), evidence("FOOD1", "ch2", "v2")]
    cats: dict[str, Category] = {"CAFE1": "CAFE", "FOOD1": "RESTAURANT"}
    assert rank_places(_aggs(evs), categories=cats, styles=["카페·포토스팟"])[0].place_id == "CAFE1"
    assert (
        rank_places(_aggs(evs), categories=cats, reference_channel_ids=["ch2"])[0].place_id
        == "FOOD1"
    )


def test_value_style_uses_price_positive() -> None:
    evs = [evidence("A", "ch1", "v1"), evidence("B", "ch2", "v2", ratings={"price": "POSITIVE"})]
    assert rank_places(_aggs(evs), categories={}, styles=["가성비"])[0].place_id == "B"


def test_mentioned_only_place_is_not_ranked() -> None:
    evs = [evidence("A", "ch1", "v1"), evidence("M", "ch2", "v2", visit="MENTIONED")]
    assert [r.place_id for r in rank_places(_aggs(evs), categories={})] == ["A"]


def test_ties_are_deterministic() -> None:
    evs = [evidence("Z", "ch1", "v1"), evidence("A", "ch2", "v2")]
    assert [r.place_id for r in rank_places(_aggs(evs), categories={})] == ["A", "Z"]


def test_ranking_takes_no_popularity_metrics() -> None:
    banned = ("view", "like", "subscriber", "published", "upload")
    params = [
        p for fn in (ranking.score, ranking.rank_places) for p in inspect.signature(fn).parameters
    ]
    assert not [p for p in params if any(b in p.lower() for b in banned)]

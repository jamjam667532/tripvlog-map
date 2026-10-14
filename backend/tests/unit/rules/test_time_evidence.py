from collections.abc import Sequence

from shared.rules.time_evidence import summarize_time_evidence
from shared.schemas.items import PlaceEvidenceItem

from .factories import evidence

NIGHT_SCENE = {"kind": "SCENE", "situation": "NIGHT"}
OPENING_WAIT = {"kind": "WAIT_EXPERIENCE", "situation": "OPENING"}


def _summary(evs: Sequence[PlaceEvidenceItem]) -> dict[tuple[str, str], tuple[int, bool]]:
    return {(s.kind, s.situation): (s.channels, s.recommend) for s in summarize_time_evidence(evs)}


def test_night_scene_only_is_not_recommended() -> None:
    # §8 필수: SCENE NIGHT만 있음 → recommend=false
    evs = [evidence("P", f"ch{i}", f"v{i}", time=[NIGHT_SCENE]) for i in range(5)]
    assert _summary(evs) == {("SCENE", "NIGHT"): (5, False)}


def test_stated_time_clock_never_leaks_into_other_kinds() -> None:
    # §8 필수: STATED_TIME 외 kind의 localClockTime은 null (스키마가 강제, 저장 아이템까지 유지)
    e = evidence("P", "ch1", "v1", time=[{**OPENING_WAIT, "localClockTime": "10:00"}])
    assert e.visit_time_evidence[0].local_clock_time is None


def test_creator_tip_is_recommended_even_from_one_mention() -> None:
    tip = {"kind": "CREATOR_TIP", "situation": "OPENING"}
    assert _summary([evidence("P", "ch1", "v1", visit="MENTIONED", time=[tip])]) == {
        ("CREATOR_TIP", "OPENING"): (1, True)
    }


def test_short_wait_in_two_channels_is_recommended() -> None:
    evs = [
        evidence("P", "ch1", "v1", ratings={"wait": "POSITIVE"}, time=[OPENING_WAIT]),
        evidence("P", "ch2", "v2", ratings={"wait": "POSITIVE"}, time=[OPENING_WAIT]),
    ]
    assert _summary(evs) == {("WAIT_EXPERIENCE", "OPENING"): (2, True)}


def test_short_wait_in_one_channel_counted_twice_is_not_recommended() -> None:
    evs = [
        evidence("P", "ch1", "v1", 10, ratings={"wait": "POSITIVE"}, time=[OPENING_WAIT]),
        evidence("P", "ch1", "v1", 90, ratings={"wait": "POSITIVE"}, time=[OPENING_WAIT]),
    ]
    assert _summary(evs) == {("WAIT_EXPERIENCE", "OPENING"): (1, False)}


def test_conflicting_waits_listed_without_recommend() -> None:
    lunch = {"kind": "WAIT_EXPERIENCE", "situation": "LUNCH_PEAK"}
    evs = [
        evidence("P", "ch1", "v1", ratings={"wait": "NEGATIVE"}, time=[lunch]),
        evidence("P", "ch2", "v2", ratings={"wait": "NEGATIVE"}, time=[lunch]),
        evidence("P", "ch3", "v3", ratings={"wait": "POSITIVE"}, time=[OPENING_WAIT]),
    ]
    assert _summary(evs) == {
        ("WAIT_EXPERIENCE", "LUNCH_PEAK"): (2, False),
        ("WAIT_EXPERIENCE", "OPENING"): (1, False),
    }


def test_visit_based_evidence_from_mention_is_ignored() -> None:
    evs = [
        evidence(
            "P", "ch1", "v1", visit="MENTIONED", ratings={"wait": "POSITIVE"}, time=[OPENING_WAIT]
        )
    ]
    assert _summary(evs) == {}

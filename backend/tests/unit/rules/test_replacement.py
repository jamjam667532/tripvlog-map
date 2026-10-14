from shared.rules.replacement import choose_replacement
from shared.schemas.items import SpareVideo

from .factories import ref


def spare(video_id: str, channel_id: str, duration: int) -> SpareVideo:
    return SpareVideo(video_id=video_id, channel_id=channel_id, duration_sec=duration)


REFS = [ref("v1", "ch1"), ref("v2", "ch2", state="FAILED")]
SPARES = [spare("s1", "ch5", 900), spare("s2", "ch6", 300), spare("s3", "ch7", 1200)]


def test_already_analyzed_spare_is_preferred_even_if_longer() -> None:
    pick = choose_replacement(SPARES, REFS, analyzed_video_ids={"s3"}, max_replacements=1)
    assert pick is not None and pick.video_id == "s3"


def test_shortest_spare_when_nothing_cached() -> None:
    pick = choose_replacement(SPARES, REFS, analyzed_video_ids=set(), max_replacements=1)
    assert pick is not None and pick.video_id == "s2"


def test_cap_reached_returns_none() -> None:
    refs = [*REFS, ref("s2", "ch6", replaces="v2")]
    assert choose_replacement(SPARES, refs, analyzed_video_ids=set(), max_replacements=1) is None


def test_spare_from_used_channel_is_skipped() -> None:
    spares = [spare("s9", "ch1", 100), spare("s2", "ch6", 300)]
    pick = choose_replacement(spares, REFS, analyzed_video_ids={"s9"}, max_replacements=1)
    assert pick is not None and pick.video_id == "s2"


def test_no_spares_returns_none() -> None:
    assert choose_replacement([], REFS, analyzed_video_ids=set(), max_replacements=1) is None

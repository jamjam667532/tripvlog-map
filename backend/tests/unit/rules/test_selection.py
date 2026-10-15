from datetime import UTC, datetime, timedelta

from shared.rules.selection import merge_round_robin, select_videos
from shared.rules.style_tags import style_tag, video_styles
from shared.schemas.youtube import VideoMeta

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def meta(
    vid: str,
    ch: str,
    *,
    minutes: int = 15,
    days_ago: int = 30,
    privacy: str = "public",
    title: str = "오사카 브이로그",
) -> VideoMeta:
    return VideoMeta.model_validate(
        {
            "video_id": vid,
            "channel_id": ch,
            "title": title,
            "description": "",
            "duration_sec": minutes * 60,
            "privacy_status": privacy,
            "published_at": NOW - timedelta(days=days_ago),
        }
    )


def ids(metas: list[VideoMeta]) -> list[str]:
    return [m.video_id for m in metas]


def test_merge_round_robin_interleaves_and_dedupes() -> None:
    assert merge_round_robin([["a", "b", "c"], ["x", "a"], ["y"]]) == ["a", "x", "y", "b", "c"]
    assert merge_round_robin([]) == []


def test_filters_private_short_and_old_videos() -> None:
    picked = select_videos(
        [
            meta("ok", "c1"),
            meta("private", "c2", privacy="unlisted"),
            meta("short", "c3", minutes=2),
            meta("old", "c4", days_ago=731),
            meta("edge", "c5", minutes=3, days_ago=730),
        ],
        now=NOW,
        max_videos=5,
        max_spares=3,
    )
    assert ids(picked.chosen) == ["ok", "edge"]


def test_one_video_per_channel_and_spares_from_other_channels() -> None:
    picked = select_videos(
        [meta("a1", "A"), meta("a2", "A"), meta("b1", "B"), meta("c1", "C"), meta("d1", "D")],
        now=NOW,
        max_videos=2,
        max_spares=3,
    )
    assert ids(picked.chosen) == ["a1", "b1"]
    assert ids(picked.spares) == ["c1", "d1"]


def test_duplicate_video_ids_counted_once() -> None:
    picked = select_videos([meta("a", "A"), meta("a", "A")], now=NOW, max_videos=5, max_spares=3)
    assert ids(picked.chosen) == ["a"]


def test_preferred_style_first_but_channel_count_wins() -> None:
    picked = select_videos(
        [
            meta("plain", "A"),
            meta("b-plain", "B"),
            meta("b-food", "B", title="오사카 맛집 투어"),
            meta("c-food", "C", title="라멘 먹방"),
        ],
        now=NOW,
        preferred_styles=["맛집"],
        max_videos=3,
        max_spares=0,
    )
    # 채널 B는 맛집 영상으로 바뀌고, 맛집 채널이 앞으로. 맛집이 아닌 채널 A도 버리지 않는다
    assert ids(picked.chosen) == ["b-food", "c-food", "plain"]


def test_style_tags() -> None:
    assert style_tag("오사카 맛집 브이로그") == "맛집"
    assert style_tag("교토 카페 투어와 신사 산책") == "복합"
    assert style_tag("일상 브이로그") == "분류불가"
    assert video_styles("돈키호테 쇼핑 하울", "") == {"쇼핑"}

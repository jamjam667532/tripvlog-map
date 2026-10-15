from shared.rules.area import area_groups
from shared.rules.evidence import choose_display_name


def test_nearby_places_share_area_and_labels_follow_rank() -> None:
    groups = area_groups(
        [
            ("dotonbori-1", 34.6687, 135.5013),
            ("umeda", 34.7025, 135.4959),  # 약 4 km 북쪽
            ("dotonbori-2", 34.6690, 135.5020),
        ]
    )
    assert groups == {"dotonbori-1": "지역 1", "umeda": "지역 2", "dotonbori-2": "지역 1"}


def test_area_groups_empty() -> None:
    assert area_groups([]) == {}


def test_choose_display_name_majority_then_channel_order() -> None:
    assert choose_display_name(
        [("c2", "이치란"), ("c1", "이치란 · 도톤보리"), ("c3", "이치란")]
    ) == ("이치란")
    assert choose_display_name([("c2", "B"), ("c1", "A")]) == "A"
    assert choose_display_name([]) is None

from shared.rules.matching import match_candidate, name_similarity, normalize
from shared.schemas.places import GeoPoint, PlaceHit

DOTONBORI = GeoPoint(lat=34.6687, lng=135.5013)


def hit(
    place_id: str, name: str, address: str = "", lat: float = 34.6687, lng: float = 135.5013
) -> PlaceHit:
    return PlaceHit(
        place_id=place_id, name=name, address=address, location=GeoPoint(lat=lat, lng=lng)
    )


def test_normalize_unifies_width_case_and_spacing() -> None:
    fullwidth = "".join(chr(ord(c) + 0xFEE0) for c in "ICHIRAN")  # 전각 영문
    assert normalize(f"{fullwidth}  Dōtonbori!") == normalize("ichiran dōtonbori")


def test_alias_in_other_script_matches() -> None:
    assert name_similarity(["이치란", "一蘭"], "一蘭 道頓堀店") == 1.0


def test_single_branch_is_confirmed() -> None:
    out = match_candidate(
        ["이치란"],
        "도톤보리",
        [
            hit("A", "이치란 도톤보리점", "오사카시 주오구 도톤보리 1-4"),
            hit("B", "이치란 난바점", "오사카시 주오구 난바"),
        ],
    )
    assert (out.status, out.place_id) == ("CONFIRMED", "A")


def test_two_chain_branches_remaining_is_unconfirmed() -> None:
    # §8 필수: 체인 지점 2개 남음 → UNCONFIRMED (후보 보존)
    hits = [
        hit("A", "이치란 도톤보리점 본관", "오사카시 주오구 도톤보리 1-4"),
        hit("B", "이치란 도톤보리점 별관", "오사카시 주오구 도톤보리 1-6"),
    ]
    out = match_candidate(["이치란"], "도톤보리", hits)
    assert out.status == "UNCONFIRMED"
    assert out.place_ids == ("A", "B")
    assert out.place_id is None


def test_branch_hint_tokens_narrow_to_one_branch() -> None:
    hits = [
        hit("A", "이치란 도톤보리점 본관", "도톤보리 1-4"),
        hit("B", "이치란 도톤보리점 별관", "도톤보리 1-6"),
    ]
    out = match_candidate(["이치란"], "도톤보리 별관", hits)
    assert (out.status, out.place_id) == ("CONFIRMED", "B")


def test_without_branch_hint_two_branches_stay_unconfirmed() -> None:
    hits = [hit("A", "이치란 도톤보리점"), hit("B", "이치란 난바점")]
    assert match_candidate(["이치란"], None, hits).status == "UNCONFIRMED"


def test_no_similar_name_is_discarded() -> None:
    out = match_candidate(["이치란"], None, [hit("X", "킨류 라멘")])
    assert out.status == "DISCARDED"
    assert out.place_ids == ()


def test_branch_hint_not_found_is_discarded() -> None:
    out = match_candidate(["이치란"], "우메다", [hit("A", "이치란 도톤보리점", "도톤보리")])
    assert out.status == "DISCARDED"


def test_duplicate_hits_from_multiple_queries_count_once() -> None:
    hits = [hit("A", "이치란 도톤보리점"), hit("A", "이치란 도톤보리점")]
    assert match_candidate(["이치란"], None, hits).status == "CONFIRMED"


def test_distance_used_only_when_location_clue_given() -> None:
    hits = [hit("A", "이치란 도톤보리점"), hit("B", "이치란 우메다점", lat=34.7025, lng=135.4959)]
    assert match_candidate(["이치란"], None, hits).status == "UNCONFIRMED"
    out = match_candidate(["이치란"], None, hits, near=DOTONBORI, near_radius_m=500)
    assert (out.status, out.place_id) == ("CONFIRMED", "A")


def test_hit_repr_hides_name_and_coordinates() -> None:
    text = repr(hit("A", "이치란 도톤보리점", "도톤보리 1-4"))
    assert "이치란" not in text and "34.66" not in text and "도톤보리" not in text

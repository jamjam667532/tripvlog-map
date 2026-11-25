"""[M8] 관심사 기반 테마 추천 규칙 (결정 0011)."""

from datetime import UTC, datetime, timedelta

import pytest

from shared.rules.interests import (
    LEXICAL_BONUS,
    SUBSCRIBED_THEME,
    Themed,
    active_interests,
    compose,
    cosine,
    mean_vector,
    place_theme_boosts,
    term_words,
    theme_queries,
    theme_score,
    validate_interests,
)
from shared.rules.selection import Selection
from shared.schemas.items import UserInterest, UserItem, UserPreferences, YoutubeLink
from shared.schemas.taste import InterestProposal
from shared.schemas.youtube import VideoMeta

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def interest(label: str, vec: list[float], weight: float = 0.5, term: str = "투어") -> UserInterest:
    return UserInterest(
        label=label,
        weight=weight,
        search_terms=[f"{label} {term}"],
        evidence_ids=["c"],
        embedding=vec,
    )


def meta(vid: str, ch: str) -> VideoMeta:
    return VideoMeta(
        video_id=vid,
        channel_id=ch,
        title="t",
        description="",
        duration_sec=900,
        privacy_status="public",
        published_at=NOW,
    )


def test_validate_interests_keeps_only_evidence_in_input_and_weights_by_count() -> None:
    proposals = [
        InterestProposal(
            label="건축", evidence_ids=["c1", "c2", "made-up"], search_terms=["건축 투어", " "]
        ),
        InterestProposal(label="역사", evidence_ids=["v1"], search_terms=[]),
        InterestProposal(label="가짜", evidence_ids=["nope"], search_terms=["x"]),
        InterestProposal(label="건축", evidence_ids=["c3"], search_terms=["중복"]),
    ]
    out = validate_interests(proposals, {"c1", "c2", "c3", "v1"})
    assert [(i.label, i.weight, i.evidence_ids) for i in out] == [
        ("건축", 0.67, ["c1", "c2"]),
        ("역사", 0.33, ["v1"]),
    ]
    assert out[0].search_terms == ["건축 투어"]
    assert out[1].search_terms == ["역사 여행"]  # 검색어가 없으면 이름으로 만든다


def test_validate_interests_caps_count_and_length() -> None:
    many = [InterestProposal(label=f"관심사{i}" * 5, evidence_ids=["c"]) for i in range(8)]
    out = validate_interests(many, {"c"}, max_interests=5)
    assert len(out) == 5 and all(len(i.label) <= 20 for i in out)


def test_cosine_and_theme_score_use_interest_weight() -> None:
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 0]) == 0.0
    arch = interest("건축", [1.0, 0.0, 0.0], weight=1.0)
    anime = interest("애니", [0.0, 1.0, 0.0], weight=0.0)
    label, score = theme_score([0.9, 0.1, 0.0], [arch, anime])
    assert label == "건축" and score == pytest.approx(0.9939, abs=1e-3)
    label, score = theme_score([0.0, 1.0, 0.0], [arch, anime])
    assert label == "애니" and score == pytest.approx(0.8)  # 비중 0이면 0.8배
    assert theme_score([0.0, 0.0, 1.0], [arch]) == (None, 0.0)


def test_theme_queries_use_top_interests_first_term() -> None:
    ints = [interest("건축", [1.0]), interest("애니", [1.0]), interest("역사", [1.0])]
    assert theme_queries(ints, " 도쿄 ") == ["도쿄 건축 투어", "도쿄 애니 투어"]


def test_active_interests_skip_hidden_ones() -> None:
    link = YoutubeLink.model_validate(
        {
            "linked": True,
            "syncedAt": NOW.isoformat(),
            "resyncDueAt": (NOW + timedelta(days=25)).isoformat(),
        }
    ).model_copy(update={"interests": [interest("건축", [1.0]), interest("애니", [1.0])]})
    user = UserItem(
        user_id="u", youtube=link, preferences=UserPreferences(hidden_interests=["애니"])
    )
    assert [i.label for i in active_interests(user, NOW)] == ["건축"]
    assert active_interests(None, NOW) == [] and active_interests(UserItem(user_id="u"), NOW) == []
    assert active_interests(user, NOW + timedelta(days=25)) == []  # 25일 지나면 만료


def test_compose_three_personalized_then_general() -> None:
    general = Selection(
        chosen=[meta(f"g{i}", f"gc{i}") for i in range(5)], spares=[meta("s1", "sc1")]
    )
    personal = [meta("p1", "pc1")]
    themed = [
        Themed(meta("t1", "tc1"), "건축", 0.40),
        Themed(meta("t2", "tc2"), "애니", 0.30),
        Themed(meta("t3", "tc3"), "건축", 0.10),  # 기준 미만
        Themed(meta("t4", "pc1"), "건축", 0.50),  # 구독 채널과 같은 채널 → 제외
    ]
    sel, themes = compose(general, personal, themed, max_videos=5, max_spares=2)
    assert [m.video_id for m in sel.chosen] == ["p1", "t1", "t2", "g0", "g1"]
    assert [m.video_id for m in sel.spares] == ["g2", "g3"]
    assert themes == {"p1": (SUBSCRIBED_THEME, None), "t1": ("건축", 0.40), "t2": ("애니", 0.30)}


def test_compose_falls_back_to_general_when_nothing_matches() -> None:
    general = Selection(chosen=[meta(f"g{i}", f"gc{i}") for i in range(5)], spares=[])
    sel, themes = compose(
        general, [], [Themed(meta("t", "tc"), "건축", 0.1)], max_videos=5, max_spares=3
    )
    assert [m.video_id for m in sel.chosen] == [f"g{i}" for i in range(5)] and themes == {}


def test_place_theme_boosts_take_best_video_score() -> None:
    boosts, names = place_theme_boosts(
        {"P1": {"v1", "v2"}, "P2": {"v3"}, "P3": {"v4"}},
        {"v1": ("건축", 0.3), "v2": ("애니", 0.5), "v3": (SUBSCRIBED_THEME, None)},
    )
    assert boosts == {"P1": 0.5}
    assert names == {"P1": ["건축", "애니"], "P2": [SUBSCRIBED_THEME]}


def test_keyword_in_video_text_adds_bonus() -> None:
    """2026-11-25 시험: "현대건축"처럼 임베딩이 약하게 보는 경우를 단어 일치가 보완한다."""
    arch = interest("건축", [1.0, 0.0], weight=1.0, term="투어")  # 검색어 "건축 투어"
    label, plain = theme_score([0.2, 1.0], [arch])
    label2, boosted = theme_score([0.2, 1.0], [arch], "도쿄 현대건축 산책")
    assert label == label2 == "건축"
    assert boosted == pytest.approx(plain + LEXICAL_BONUS)
    _, none = theme_score([0.2, 1.0], [arch], "도쿄 투어 브이로그")  # "투어"는 흔한 말이라 제외
    assert none == pytest.approx(plain)


def test_term_words_and_mean_vector() -> None:
    assert term_words(["건축 투어", "애니 성지순례", "여행"]) == {"건축", "애니", "성지순례"}
    assert mean_vector([[1.0, 0.0], [0.0, 1.0]]) == [0.5, 0.5]


def test_clean_description_drops_sponsor_links_and_hashtag_lines() -> None:
    from shared.rules.interests import clean_description

    raw = """본 영상은 OO호텔로부터 숙박을 제공받아 제작되었습니다
📩 비즈니스 문의 travel@example.com
📷 인스타그램 @tokyo_walker
https://instagram.com/tokyo_walker
#도쿄 #건축 #브이로그
안도 다다오의 건축물을 따라 오모테산도를 걸었어요
두 번째로 들른 곳은 국립신미술관입니다"""
    assert clean_description(raw) == (
        "안도 다다오의 건축물을 따라 오모테산도를 걸었어요 두 번째로 들른 곳은 국립신미술관입니다"
    )


def test_video_text_joins_title_cleaned_description_and_tags() -> None:
    from shared.rules.interests import video_text

    m = meta("v", "c").model_copy(
        update={
            "title": "도쿄 건축 산책",
            "description": "협찬 문의는 메일로\n쿠마 켄고 건축을 봤어요",
            "tags": ["안도다다오", "건축여행"],
        }
    )
    assert video_text(m) == "도쿄 건축 산책\n쿠마 켄고 건축을 봤어요\n안도다다오 건축여행"

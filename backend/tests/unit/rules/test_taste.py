"""[M8] 취향 분석 규칙 (결정 0010)."""

from datetime import UTC, datetime

from shared.rules.aggregation import aggregate_places
from shared.rules.ranking import rank_places
from shared.rules.selection import Selection, select_videos
from shared.rules.taste import (
    TasteProfile,
    accept_label,
    auto_travel_channels,
    combined_style_profile,
    destination_uploads,
    personal_first,
    profile_of,
    style_profile,
    style_similarity,
    travel_candidates,
    video_taste_score,
)
from shared.schemas.common import Category, Style
from shared.schemas.items import UserItem, UserPreferences, VideoRef, YoutubeLink
from shared.schemas.taste import ChannelInfo, ChannelTasteLabel, ChannelVideo
from shared.schemas.youtube import VideoMeta
from tests.unit.rules.factories import evidence


def ch(cid: str, title: str = "", description: str = "") -> ChannelInfo:
    return ChannelInfo(channel_id=cid, title=title, description=description)


def vid(vid_: str, cid: str, title: str = "", description: str = "") -> ChannelVideo:
    return ChannelVideo(video_id=vid_, channel_id=cid, title=title, description=description)


def meta(vid_: str, cid: str) -> VideoMeta:
    return VideoMeta(
        video_id=vid_,
        channel_id=cid,
        title="오사카 브이로그",
        description="",
        duration_sec=900,
        privacy_status="public",
        published_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def test_travel_candidates_keep_travel_channels_and_liked_travel_first() -> None:
    channels = [
        ch("game", "게임 방송"),
        ch("trip", "주말 여행 브이로그"),
        ch("food", "먹방 채널"),  # 이름에는 여행 표기가 없지만 좋아요한 여행 영상이 있다
        ch("news", "뉴스"),
    ]
    liked = [
        vid("a", "food", "오사카 맛집 투어"),
        vid("b", "food", "도쿄 여행 3일"),
        vid("c", "game"),
    ]
    picked = [c.channel_id for c in travel_candidates(channels, liked)]
    assert picked == ["food", "trip"]


def test_travel_candidates_are_capped() -> None:
    channels = [ch(f"c{i}", "해외여행") for i in range(50)]
    assert len(travel_candidates(channels, [], max_candidates=40)) == 40


def test_label_kept_only_when_evidence_is_in_channel_text() -> None:
    channel = ch("trip", "주말 여행 브이로그", "매주 일본 소도시를 걷습니다")
    good = ChannelTasteLabel(
        channel_id="trip", travel="YES", styles=["관광·역사"], evidence="일본 소도시를 걷습니다"
    )
    assert accept_label(good, channel) == good

    made_up = ChannelTasteLabel(
        channel_id="trip", travel="YES", styles=["맛집"], evidence="미슐랭 맛집만 갑니다"
    )
    lowered = accept_label(made_up, channel)
    assert lowered.travel == "UNKNOWN" and lowered.styles == [] and lowered.evidence is None

    no_evidence = ChannelTasteLabel(channel_id="trip", travel="NO")
    assert accept_label(no_evidence, channel).travel == "UNKNOWN"


def test_style_profile_counts_style_keywords_only() -> None:
    videos = [
        vid("a", "c", "오사카 맛집 투어"),
        vid("b", "c", "라멘 먹방"),
        vid("c", "c", "교토 카페 투어"),
        vid("d", "c", "출국 브이로그"),  # 스타일 표기 없음 → 세지 않는다
    ]
    assert style_profile(videos) == {"맛집": 0.67, "카페·포토스팟": 0.33}
    assert style_profile([]) == {}


def test_destination_uploads_use_aliases() -> None:
    uploads = [
        vid("a", "c", "大阪 3박 4일"),
        vid("b", "c", "도쿄 맛집"),
        vid("c", "c", "osaka night"),
    ]
    assert [v.video_id for v in destination_uploads(uploads, "오사카")] == ["a", "c"]


def test_personal_first_puts_up_to_two_personal_videos_one_per_channel() -> None:
    general = Selection(
        chosen=[meta(f"g{i}", f"gc{i}") for i in range(5)],
        spares=[meta("s1", "sc1"), meta("s2", "sc2")],
    )
    personal = [meta("p1", "pc1"), meta("p2", "pc1"), meta("p3", "pc2"), meta("p4", "pc3")]
    out = personal_first(general, personal, max_videos=5, max_spares=3)
    assert [m.video_id for m in out.chosen] == ["p1", "p3", "g0", "g1", "g2"]
    assert [m.video_id for m in out.spares] == ["g3", "g4", "s1"]


def test_personal_first_skips_general_videos_from_personal_channels() -> None:
    general = Selection(chosen=[meta("g0", "pc1"), meta("g1", "gc1")], spares=[])
    out = personal_first(general, [meta("p1", "pc1")], max_videos=5, max_spares=3)
    assert [m.video_id for m in out.chosen] == ["p1", "g1"]


def test_personal_first_without_personal_is_unchanged() -> None:
    general = Selection(chosen=[meta("g0", "c0")], spares=[meta("s0", "c1")])
    assert personal_first(general, [], max_videos=5, max_spares=3) == general


# ---------- 취향 프로필·유사도 (결정 0010 개정) ----------


NOW_T = datetime(2026, 11, 1, tzinfo=UTC)


def _link(channels: list[str], weights: dict[str, float]) -> YoutubeLink:
    return YoutubeLink.model_validate(
        {
            "linked": True,
            "syncedAt": NOW_T.isoformat(),
            "resyncDueAt": NOW_T.isoformat(),
            "travelChannelIds": channels,
            "styleProfileCandidate": weights,
        }
    )


def test_auto_travel_channels_from_labels_or_many_travel_likes() -> None:
    labels = {
        "yes": ChannelTasteLabel(channel_id="yes", travel="YES", evidence="x"),
        "unk": ChannelTasteLabel(channel_id="unk", travel="UNKNOWN"),
        "no": ChannelTasteLabel(channel_id="no", travel="NO", evidence="x"),
    }
    liked = [
        vid("a", "unk", "오사카 여행"),
        vid("b", "unk", "도쿄 브이로그"),
        vid("c", "one", "교토 여행"),
    ]
    assert auto_travel_channels(labels, liked) == ["unk", "yes"]  # unk: 여행 좋아요 2개, one: 1개


def test_combined_style_profile_uses_likes_and_travel_channel_labels() -> None:
    labels = {"t": ChannelTasteLabel(channel_id="t", travel="YES", styles=["카페·포토스팟"])}
    liked = [vid("a", "x", "오사카 맛집 여행"), vid("b", "x", "도쿄 라멘 여행")]
    assert combined_style_profile(liked, labels) == {"맛집": 0.67, "카페·포토스팟": 0.33}


def test_profile_prefers_user_edits_over_auto() -> None:
    auto = UserItem(user_id="u", youtube=_link(["c1", "c2"], {"맛집": 0.7, "카페·포토스팟": 0.3}))
    p = profile_of(auto)
    assert p == TasteProfile(("c1", "c2"), {"맛집": 0.7, "카페·포토스팟": 0.3})

    edited = auto.model_copy(
        update={"preferences": UserPreferences(styles=["관광·역사"], reference_channel_ids=["c2"])}
    )
    assert profile_of(edited) == TasteProfile(("c2",), {"관광·역사": 1.0})
    assert profile_of(None) is None
    assert profile_of(UserItem(user_id="u")) is None


def test_style_similarity_and_video_score() -> None:
    weights: dict[Style, float] = {"맛집": 0.6, "카페·포토스팟": 0.25, "관광·역사": 0.15}
    assert style_similarity(weights, {"맛집"}) == 0.6
    assert style_similarity(weights, {"맛집", "카페·포토스팟"}) == 0.85
    assert style_similarity(weights, set()) == 0.0
    profile = TasteProfile(("subbed",), weights)
    food = meta("v1", "other")  # 제목 "오사카 브이로그": 스타일 없음
    assert video_taste_score(food, profile) == 0.0
    assert video_taste_score(meta("v2", "subbed"), profile) == 1.0  # 구독 여행 채널 가산


def test_select_videos_orders_by_taste_similarity() -> None:
    def m(vid_: str, ch: str, title: str) -> VideoMeta:
        return meta(vid_, ch).model_copy(update={"title": title})

    cands = [
        m("v1", "c1", "오사카 브이로그"),
        m("v2", "c2", "오사카 카페 투어"),
        m("v3", "c3", "오사카 맛집"),
    ]
    profile = TasteProfile((), {"맛집": 0.7, "카페·포토스팟": 0.3})
    sel = select_videos(
        cands,
        now=NOW_T,
        destination="오사카",
        max_videos=3,
        max_spares=0,
        taste_score=lambda x: video_taste_score(x, profile),
    )
    assert [x.video_id for x in sel.chosen] == ["v3", "v2", "v1"]
    guest = select_videos(cands, now=NOW_T, destination="오사카", max_videos=3, max_spares=0)
    assert [x.video_id for x in guest.chosen] == ["v1", "v2", "v3"]  # 게스트는 검색 순서


def test_ranking_adds_taste_weight_by_style_share() -> None:

    refs = [VideoRef(video_id="v1", channel_id="c1", analysis_version="v1-haiku45", state="DONE")]
    aggs = aggregate_places([evidence("P_r", "c1", "v1", 1), evidence("P_c", "c1", "v1", 2)], refs)
    cats: dict[str, Category] = {"P_r": "RESTAURANT", "P_c": "CAFE"}
    plain = rank_places(aggs, categories=cats)
    assert [r.place_id for r in plain] == ["P_c", "P_r"]  # 동점 → placeId 순
    tasted = rank_places(aggs, categories=cats, style_weights={"맛집": 0.8, "카페·포토스팟": 0.2})
    assert [r.place_id for r in tasted] == ["P_r", "P_c"]

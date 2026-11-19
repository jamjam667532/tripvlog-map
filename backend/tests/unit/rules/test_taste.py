"""[M8] 취향 분석 규칙 (결정 0010)."""

from datetime import UTC, datetime

from shared.rules.selection import Selection
from shared.rules.taste import (
    accept_label,
    destination_uploads,
    personal_first,
    style_profile,
    travel_candidates,
)
from shared.schemas.taste import ChannelInfo, ChannelTasteLabel, ChannelVideo
from shared.schemas.youtube import VideoMeta


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

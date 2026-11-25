"""[M8] 유튜브 구독·좋아요 취향 분석 규칙 (결정 0010, 2026-11-25 개정). 순수 함수.

취향 프로필은 연결할 때 자동으로 만든다: 구독 중 여행 채널 + 스타일 비율(맛집 0.6 …).
사용자가 화면에서 고치면 그 값이 우선한다. 추천은 콘텐츠 유사도(스타일 비율과 겹치는 정도)로 한다.

- 1차 거르기: 채널 이름·설명, 좋아요 영상 제목에 여행 표기가 있는 채널만 Bedrock에 보낸다.
- 라벨 받아들이기: Bedrock 근거(evidence)가 입력 원문에 없으면 UNKNOWN으로 낮춘다.
- 스타일 비율: 좋아요한 여행 영상 제목에 기존 스타일 키워드 규칙을 쓴다.
- 개인 영상: 사용자가 확인한 채널의 영상을 최대 2개(일반 영상 자리를 대신해 요청당 5개는 그대로).
구독자 수·좋아요 수 같은 인기 지표는 쓰지 않는다.
"""

import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from shared.rules.selection import DESTINATION_ALIASES, Selection, text_mentions_destination
from shared.rules.style_tags import video_styles
from shared.schemas.common import Style
from shared.schemas.items import UserItem, YoutubeLink
from shared.schemas.taste import ChannelInfo, ChannelTasteLabel, ChannelVideo
from shared.schemas.youtube import VideoMeta

MAX_CANDIDATES = 40  # Bedrock에 보내는 채널 상한
MAX_PERSONAL_VIDEOS = 2  # 요청 5개 중 개인 채널 영상 상한
MIN_LIKED_FOR_TRAVEL = 2  # 좋아요한 여행 영상이 이만큼 있으면 라벨 없이도 여행 채널로 본다
SUBSCRIBED_BONUS = 1.0  # 영상 추천: 구독 여행 채널 영상에 더하는 점수(유사도는 0~1)
# TODO(tune): 실제 구독 목록으로 조정한다
TRAVEL_KEYWORDS: tuple[str, ...] = (
    "여행",
    "브이로그",
    "vlog",
    "해외",
    "travel",
    "trip",
    "투어",
    "배낭",
    "세계",
    *(name for names in DESTINATION_ALIASES.values() for name in names),
)


def _norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def is_travel_text(text: str) -> bool:
    t = _norm(text)
    return any(_norm(k) in t for k in TRAVEL_KEYWORDS)


def travel_liked(liked: Iterable[ChannelVideo]) -> list[ChannelVideo]:
    return [v for v in liked if is_travel_text(f"{v.title}\n{v.description}")]


def travel_candidates(
    channels: Sequence[ChannelInfo],
    liked: Sequence[ChannelVideo],
    *,
    max_candidates: int = MAX_CANDIDATES,
) -> list[ChannelInfo]:
    """여행 표기가 있는 채널. 좋아요한 여행 영상이 많은 채널을 앞에, 같으면 입력 순서."""
    liked_counts = Counter(v.channel_id for v in travel_liked(liked))
    picked = [
        c
        for c in channels
        if c.channel_id in liked_counts or is_travel_text(f"{c.title}\n{c.description}")
    ]
    picked.sort(key=lambda c: -liked_counts[c.channel_id])
    return picked[:max_candidates]


def accept_label(label: ChannelTasteLabel, channel: ChannelInfo) -> ChannelTasteLabel:
    """근거가 입력 원문에 그대로 있을 때만 YES·NO와 스타일을 받아들인다. 아니면 UNKNOWN."""
    source = _norm(f"{channel.title}\n{channel.description}")
    evidence = _norm(label.evidence or "")
    if evidence and evidence in source:
        return label
    return ChannelTasteLabel(channel_id=label.channel_id, travel="UNKNOWN")


def style_profile(videos: Iterable[ChannelVideo]) -> dict[Style, float]:
    """여행 영상 제목·설명의 스타일 비율(합 1). 스타일 표기가 없는 영상은 세지 않는다."""
    counts: Counter[Style] = Counter()
    for v in videos:
        counts.update(video_styles(v.title, v.description))
    total = sum(counts.values())
    if total == 0:
        return {}
    return {style: round(n / total, 2) for style, n in counts.most_common()}


def destination_uploads(uploads: Iterable[ChannelVideo], destination: str) -> list[ChannelVideo]:
    return [
        v for v in uploads if text_mentions_destination(f"{v.title}\n{v.description}", destination)
    ]


def personal_first(
    selection: Selection,
    personal: Sequence[VideoMeta],
    *,
    max_videos: int,
    max_spares: int,
    max_personal: int = MAX_PERSONAL_VIDEOS,
) -> Selection:
    """개인 채널 영상을 앞에 최대 max_personal개 넣고 나머지를 일반 선택으로 채운다.

    채널당 1개 원칙은 그대로다. 개인 영상이 없으면 원래 선택과 같다.
    """
    chosen: list[VideoMeta] = []
    channels: set[str] = set()
    for meta in personal:
        if len(chosen) >= max_personal:
            break
        if meta.channel_id not in channels:
            channels.add(meta.channel_id)
            chosen.append(meta)
    if not chosen:
        return selection
    ids = {m.video_id for m in chosen}
    rest = [
        m
        for m in [*selection.chosen, *selection.spares]
        if m.channel_id not in channels and m.video_id not in ids
    ]
    room = max(0, max_videos - len(chosen))
    return Selection(chosen=chosen + rest[:room], spares=rest[room : room + max_spares])


# ---------- 취향 프로필 (결정 0010 개정: 자동 분석 + 사용자 수정 우선) ----------


@dataclass(frozen=True)
class TasteProfile:
    travel_channel_ids: tuple[str, ...]  # 순서 있음(좋아요 많은 순 또는 사용자가 고친 순)
    style_weights: dict[Style, float]  # 합 1. 비어 있으면 스타일 취향 없음


def auto_travel_channels(
    labels: Mapping[str, ChannelTasteLabel], liked: Sequence[ChannelVideo]
) -> list[str]:
    """여행 채널: Bedrock이 근거와 함께 YES로 본 채널, 또는 좋아요한 여행 영상이 많은 채널."""
    liked_counts = Counter(v.channel_id for v in travel_liked(liked))
    chosen = {cid for cid, label in labels.items() if label.travel == "YES"}
    chosen |= {cid for cid, n in liked_counts.items() if n >= MIN_LIKED_FOR_TRAVEL}
    # 좋아요가 많은 순, 같으면 채널 ID 순
    return sorted(chosen, key=lambda c: (-liked_counts[c], c))


def combined_style_profile(
    liked: Sequence[ChannelVideo], labels: Mapping[str, ChannelTasteLabel]
) -> dict[Style, float]:
    """좋아요한 여행 영상의 스타일 + 여행 채널 라벨의 스타일을 합친 비율(합 1)."""
    counts: Counter[Style] = Counter()
    for v in travel_liked(liked):
        counts.update(video_styles(v.title, v.description))
    for label in labels.values():
        if label.travel == "YES":
            counts.update(label.styles)
    total = sum(counts.values())
    if total == 0:
        return {}
    return {style: round(n / total, 2) for style, n in counts.most_common()}


def live_youtube(user: UserItem | None, now: datetime) -> YoutubeLink | None:
    """만료되지 않은 유튜브 연결 데이터. 연결 후 25일(resyncDueAt)이 지나면 쓰지 않는다.

    YouTube API 정책상 받은 데이터는 30일 안에 갱신·삭제해야 한다. Users 테이블은 TTL 대상이
    아니라서 읽을 때 만료를 판단한다(매일 지우는 cleanup Lambda는 두지 않는다. 결정 0011).
    """
    if user is None or user.youtube is None or now >= user.youtube.resync_due_at:
        return None
    return user.youtube


def profile_of(user: UserItem | None, now: datetime) -> TasteProfile | None:
    """실제로 쓸 취향. 사용자가 고친 값(preferences)이 우선, 없으면 유튜브에서 자동으로 만든 값."""
    if user is None:
        return None
    prefs, yt = user.preferences, live_youtube(user, now)
    channels = prefs.reference_channel_ids or (yt.travel_channel_ids if yt else [])
    if prefs.styles:
        weights = {s: round(1 / len(prefs.styles), 2) for s in prefs.styles}
    else:
        weights = dict(yt.style_profile_candidate) if yt else {}
    if not channels and not weights:
        return None
    return TasteProfile(tuple(channels), weights)


def style_similarity(weights: Mapping[Style, float], styles: Iterable[Style]) -> float:
    """취향 비율 중 대상 스타일이 차지하는 몫(0~1). 예: 맛집 0.6·카페 0.25, 맛집 영상이면 0.6."""
    return round(sum(weights.get(s, 0.0) for s in set(styles)), 4)


def video_taste_score(meta: VideoMeta, profile: TasteProfile) -> float:
    """영상 추천 점수 = 스타일 유사도 + 구독 여행 채널이면 SUBSCRIBED_BONUS."""
    s = style_similarity(profile.style_weights, video_styles(meta.title, meta.description))
    if meta.channel_id in profile.travel_channel_ids:
        s += SUBSCRIBED_BONUS
    return s

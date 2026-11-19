"""[M8] 유튜브 구독·좋아요 취향 분석 규칙 (결정 0010). 순수 함수.

- 1차 거르기: 채널 이름·설명, 좋아요 영상 제목에 여행 표기가 있는 채널만 Bedrock에 보낸다.
- 라벨 받아들이기: Bedrock 근거(evidence)가 입력 원문에 없으면 UNKNOWN으로 낮춘다.
- 스타일 비율: 좋아요한 여행 영상 제목에 기존 스타일 키워드 규칙을 쓴다.
- 개인 영상: 사용자가 확인한 채널의 영상 중 이미 분석된 영상만, 최대 2개(비용 원칙).
구독자 수·좋아요 수 같은 인기 지표는 쓰지 않는다.
"""

import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence

from shared.rules.selection import DESTINATION_ALIASES, Selection, text_mentions_destination
from shared.rules.style_tags import video_styles
from shared.schemas.common import Style
from shared.schemas.taste import ChannelInfo, ChannelTasteLabel, ChannelVideo
from shared.schemas.youtube import VideoMeta

MAX_CANDIDATES = 40  # Bedrock에 보내는 채널 상한
MAX_PERSONAL_VIDEOS = 2  # 요청 5개 중 개인 채널 영상 상한
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
    """개인 채널 영상(이미 분석된 것)을 앞에 최대 max_personal개 넣고 나머지를 일반 선택으로 채운다.

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

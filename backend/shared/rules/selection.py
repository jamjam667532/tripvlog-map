"""[1] 분석할 영상 고르기 (spec §5.1 4~6단계). 조회수·좋아요 수 등 인기 지표는 쓰지 않는다.

1. 같은 영상 제거, 공개만, 3분 <= 길이 <= 30분(결정 0006-5), 최근 2년,
   제목·설명란에 목적지 표기가 있는 영상만(결정 0008-4, 별칭은 DESTINATION_ALIASES)
2. 채널당 1개 (채널 안에서는 선호 스타일 영상을 먼저, 없으면 검색 순서상 첫 영상)
3. 선호 스타일 영상이 있는 채널을 앞으로. 채널 수 확보가 우선이므로 다른 채널을 버리지 않는다
4. 앞에서 max_videos개를 분석, 그다음 max_spares개를 예비로 (결정 0002-5)
장소 겹침으로 거르지 않는다. 재업로드 의심은 거르지 않는다(표시용 필드는 아직 없음).
"""

import unicodedata
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from shared.rules.style_tags import video_styles
from shared.schemas.common import Style
from shared.schemas.youtube import VideoMeta

MIN_DURATION_SEC = 3 * 60
MAX_DURATION_SEC = 30 * 60
# TODO(tune): 도시를 늘리면 별칭을 더한다. 키는 사용자가 입력하는 목적지 표기.
DESTINATION_ALIASES: dict[str, tuple[str, ...]] = {
    "오사카": ("오사카", "大阪", "osaka"),
    "교토": ("교토", "京都", "kyoto"),
    "도쿄": ("도쿄", "東京", "tokyo"),
    "후쿠오카": ("후쿠오카", "福岡", "fukuoka"),
}
MAX_AGE = timedelta(days=730)


@dataclass(frozen=True)
class Selection:
    chosen: list[VideoMeta]
    spares: list[VideoMeta]


def merge_round_robin(lists: Sequence[Sequence[str]]) -> list[str]:
    """여러 검색 결과를 번갈아 합친다(relevance와 date 혼합). 중복은 처음 것만."""
    merged: list[str] = []
    for i in range(max((len(x) for x in lists), default=0)):
        for x in lists:
            if i < len(x):
                merged.append(x[i])
    return list(dict.fromkeys(merged))


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def mentions_destination(meta: VideoMeta, destination: str) -> bool:
    """제목 또는 설명란에 목적지 표기(별칭 포함)가 있는가."""
    names = DESTINATION_ALIASES.get(destination.strip(), (destination.strip(),))
    text = _norm(f"{meta.title}\n{meta.description}")
    return any(_norm(n) in text for n in names if n)


def eligible(meta: VideoMeta, now: datetime, destination: str | None = None) -> bool:
    return (
        meta.privacy_status == "public"
        and MIN_DURATION_SEC <= meta.duration_sec <= MAX_DURATION_SEC
        and meta.published_at >= now - MAX_AGE
        and (destination is None or mentions_destination(meta, destination))
    )


def _prefers(meta: VideoMeta, preferred: Collection[Style]) -> bool:
    return bool(preferred) and bool(video_styles(meta.title, meta.description) & set(preferred))


def select_videos(
    candidates: Iterable[VideoMeta],
    *,
    now: datetime,
    preferred_styles: Collection[Style] = (),
    destination: str | None = None,
    max_videos: int,
    max_spares: int,
) -> Selection:
    by_channel: dict[str, list[VideoMeta]] = {}
    seen: set[str] = set()
    for meta in candidates:
        if meta.video_id in seen or not eligible(meta, now, destination):
            continue
        seen.add(meta.video_id)
        by_channel.setdefault(meta.channel_id, []).append(meta)

    picks = [
        next((m for m in videos if _prefers(m, preferred_styles)), videos[0])
        for videos in by_channel.values()
    ]
    # 안정 정렬: 같은 조건이면 검색 순서 유지
    picks.sort(key=lambda m: 0 if _prefers(m, preferred_styles) else 1)
    return Selection(chosen=picks[:max_videos], spares=picks[max_videos : max_videos + max_spares])

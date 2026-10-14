"""실패 영상 대체 선택 (결정 0002-5). 가장 싼 방법부터.

1. 이미 분석이 끝난 예비 영상(같은 analysisVersion) → 추가 비용 없음
2. 없으면 가장 짧은 예비 영상 → Gemini 비용은 영상 길이에 비례
작업당 max_replacements개까지, 이미 쓴 채널은 고르지 않는다.
"""

from collections.abc import Collection, Sequence

from shared.schemas.items import SpareVideo, VideoRef


def choose_replacement(
    spares: Sequence[SpareVideo],
    video_refs: Sequence[VideoRef],
    *,
    analyzed_video_ids: Collection[str],
    max_replacements: int,
) -> SpareVideo | None:
    used = sum(1 for r in video_refs if r.replaces is not None)
    if used >= max_replacements:
        return None
    taken_channels = {r.channel_id for r in video_refs}
    taken_videos = {r.video_id for r in video_refs}
    pool = [
        s for s in spares if s.channel_id not in taken_channels and s.video_id not in taken_videos
    ]
    if not pool:
        return None
    cached = [s for s in pool if s.video_id in analyzed_video_ids]
    # 같은 조건이면 collect가 정한 순서(앞쪽이 우선)를 따른다
    candidates = cached or pool
    return min(candidates, key=lambda s: (0 if cached else s.duration_sec, spares.index(s)))

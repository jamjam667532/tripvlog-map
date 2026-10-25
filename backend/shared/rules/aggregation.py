"""[4] 채널 단위 집계 (spec §5.5). 한 채널은 한 장소에 한 표만 가진다."""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import get_args

from shared.rules.time_evidence import summarize_time_evidence
from shared.schemas.api import JobStatus
from shared.schemas.common import RatingAspect, RatingValue
from shared.schemas.items import PlaceEvidenceItem, VideoRef
from shared.schemas.result import RatingCount, TimeEvidenceSummary

RATING_ASPECTS: tuple[RatingAspect, ...] = get_args(RatingAspect)


@dataclass(frozen=True)
class PlaceAggregate:
    place_id: str
    channels_visited: int
    denominator: int
    overall: RatingCount  # 순위 계산용. 결과 JSON에는 항목별(ratings)만 나간다
    ratings: dict[RatingAspect, RatingCount]
    time_evidence: list[TimeEvidenceSummary]
    visited_channel_ids: frozenset[str]
    evidence: list[PlaceEvidenceItem] = field(default_factory=list)


def successful_channels(video_refs: Iterable[VideoRef]) -> frozenset[str]:
    """분모: 분석에 성공한 서로 다른 채널. 실패·건너뜀 채널은 빠진다."""
    return frozenset(r.channel_id for r in video_refs if r.state == "DONE")


def job_status(video_refs: Sequence[VideoRef]) -> JobStatus:
    """종료 상태. 대체 영상으로 메워진 실패는 PARTIAL로 보지 않는다(결정 0003-4)."""
    if any(r.state in ("PENDING", "ANALYZING") for r in video_refs):
        return "RUNNING"
    if not any(r.state == "DONE" for r in video_refs):
        return "FAILED"
    covered = {r.replaces for r in video_refs if r.replaces is not None and r.state == "DONE"}
    uncovered = [r for r in video_refs if r.state == "FAILED" and r.video_id not in covered]
    return "PARTIAL" if uncovered else "SUCCEEDED"


def evidence_in_scope(
    evidences: Iterable[PlaceEvidenceItem], video_refs: Iterable[VideoRef]
) -> list[PlaceEvidenceItem]:
    """이 작업에서 분석에 성공한 영상(videoId + analysisVersion)의 확정 근거만."""
    done = {(r.video_id, r.analysis_version, r.channel_id) for r in video_refs if r.state == "DONE"}
    return [
        e
        for e in evidences
        if (e.video_id, e.analysis_version, e.channel_id) in done and e.match_status == "CONFIRMED"
    ]


def channel_rating(values: Iterable[RatingValue]) -> RatingValue:
    """한 채널의 여러 근거를 한 값으로. 상충하면 MIXED, 근거 없으면 NONE."""
    seen = {v for v in values if v in ("POSITIVE", "NEGATIVE", "MIXED")}
    if not seen:
        return "NONE"
    if seen == {"POSITIVE"}:
        return "POSITIVE"
    if seen == {"NEGATIVE"}:
        return "NEGATIVE"
    return "MIXED"


def tally(per_channel: Iterable[RatingValue]) -> RatingCount:
    values = list(per_channel)
    return RatingCount(
        positive=values.count("POSITIVE"),
        negative=values.count("NEGATIVE"),
        mixed=values.count("MIXED"),
    )


def aggregate_places(
    evidences: Iterable[PlaceEvidenceItem], video_refs: Sequence[VideoRef]
) -> list[PlaceAggregate]:
    denominator = len(successful_channels(video_refs))
    by_place: dict[str, list[PlaceEvidenceItem]] = defaultdict(list)
    for e in evidence_in_scope(evidences, video_refs):
        by_place[e.place_id].append(e)

    results = []
    for place_id, items in sorted(by_place.items()):
        # 평가는 방문(VISITED) 근거만 센다(결정 0003-1)
        visited = [e for e in items if e.visit_status == "VISITED"]
        visited_channels = frozenset(e.channel_id for e in visited)
        by_channel: dict[str, list[PlaceEvidenceItem]] = defaultdict(list)
        for e in visited:
            by_channel[e.channel_id].append(e)

        def per_channel(aspect: str, groups: dict[str, list[PlaceEvidenceItem]]) -> RatingCount:
            return tally(
                channel_rating(getattr(e.ratings, aspect) for e in group)
                for group in groups.values()
            )

        results.append(
            PlaceAggregate(
                place_id=place_id,
                channels_visited=len(visited_channels),
                denominator=denominator,
                overall=per_channel("overall", by_channel),
                ratings={a: per_channel(a, by_channel) for a in RATING_ASPECTS},
                time_evidence=summarize_time_evidence(items),
                visited_channel_ids=visited_channels,
                evidence=sorted(items, key=lambda e: (e.channel_id, e.video_time_range.start_sec)),
            )
        )
    return results

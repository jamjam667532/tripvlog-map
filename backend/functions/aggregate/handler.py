"""aggregate: 실패 영상 대체 연결과 결과 집계 (spec §5.5, 결정 0002-5·0003·0004-2).

action=replace
  대체되지 않은 FAILED 영상이 있으면 예비 영상 하나를 videoRefs에 넣고(replaces) 돌려준다.
  Step Functions는 그 영상으로 claim부터 다시 돌린 뒤 replace를 또 부른다. 없으면 replacement=null.
action=aggregate (기본)
  DONE 영상의 근거(videoId-index)와 매칭 요약으로 채널 단위 집계·시간대 근거·순위·지역 묶음을
  만들고 결과 JSON을 S3 results/{jobId}/result.json에 쓴다. 조회수 등 API 지표는 쓰지 않는다.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from botocore.exceptions import ClientError

from shared.repos import Repos, analysis_key, result_key, with_refs
from shared.rules.aggregation import aggregate_places, job_status, successful_channels
from shared.rules.area import area_groups
from shared.rules.evidence import choose_display_name
from shared.rules.ranking import rank_places
from shared.rules.replacement import choose_replacement
from shared.schemas.common import Category
from shared.schemas.events import AggregateInput, AggregateOutput, ReplaceOutput, VideoTask
from shared.schemas.items import JobItem, PlaceEvidenceItem, VideoRef
from shared.schemas.match import MatchSummary
from shared.schemas.result import EvidenceLink, JobResult, ResultPlace, UnconfirmedPlace
from shared.settings import Settings


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


# ---------- replace ----------


def _uncovered_failures(refs: Sequence[VideoRef]) -> list[VideoRef]:
    attempted = {r.replaces for r in refs if r.replaces is not None}
    return [r for r in refs if r.state == "FAILED" and r.video_id not in attempted]


def replace(job_id: str, deps: Deps) -> ReplaceOutput:
    s, repos = deps.settings, deps.repos
    job = repos.jobs.require(job_id)
    if not _uncovered_failures(job.video_refs):
        return ReplaceOutput(job_id=job.job_id)
    analyzed = repos.video_analysis.done_video_ids(
        [sp.video_id for sp in job.spare_videos], s.analysis_version
    )
    chosen: list[VideoRef] = []

    def promote(j: JobItem) -> JobItem:
        chosen.clear()
        targets = _uncovered_failures(j.video_refs)
        pick = choose_replacement(
            j.spare_videos,
            j.video_refs,
            analyzed_video_ids=analyzed,
            max_replacements=s.max_replacements_per_job,
        )
        if not targets or pick is None:
            return j
        ref = VideoRef(
            video_id=pick.video_id,
            channel_id=pick.channel_id,
            analysis_version=s.analysis_version,
            replaces=targets[0].video_id,
        )
        chosen.append(ref)
        spares = [sp for sp in j.spare_videos if sp.video_id != pick.video_id]
        return with_refs(j, [*j.video_refs, ref]).model_copy(update={"spare_videos": spares})

    repos.jobs.mutate(job_id, promote, deps.clock())
    if not chosen:
        return ReplaceOutput(job_id=job.job_id)
    ref = chosen[0]
    return ReplaceOutput(
        job_id=job.job_id,
        replacement=VideoTask(
            job_id=job.job_id,
            video_id=ref.video_id,
            channel_id=ref.channel_id,
            analysis_version=ref.analysis_version,
        ),
    )


# ---------- aggregate ----------


def _summary(repos: Repos, ref: VideoRef) -> MatchSummary | None:
    try:
        return repos.blobs.get_model(
            analysis_key(ref.video_id, ref.analysis_version, "match"), MatchSummary
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise


def _unconfirmed(summaries: Sequence[MatchSummary]) -> list[UnconfirmedPlace]:
    """같은 지점 후보 묶음(placeId 집합)은 하나로 합치고 이름은 나온 순서대로 모은다."""
    merged: dict[frozenset[str], list[str]] = {}
    for summary in summaries:
        for u in summary.unconfirmed:
            names = merged.setdefault(frozenset(u.place_ids), [])
            names.extend(n for n in u.names if n not in names)
    return [UnconfirmedPlace(names=names, reason="MULTIPLE_BRANCHES") for names in merged.values()]


def _finish_pending(job: JobItem) -> JobItem:
    """집계 시점에 끝나지 않은 영상은 건너뜀(SKIPPED)으로 둔다."""
    refs = [
        r.model_copy(update={"state": "SKIPPED"}) if r.state in ("PENDING", "ANALYZING") else r
        for r in job.video_refs
    ]
    return with_refs(job, refs)


def aggregate(job_id: str, deps: Deps) -> AggregateOutput:
    repos = deps.repos
    now = deps.clock()
    job = repos.jobs.mutate(job_id, _finish_pending, now)
    refs = job.video_refs
    done = [r for r in refs if r.state == "DONE"]

    evidences: list[PlaceEvidenceItem] = []
    summaries: list[tuple[VideoRef, MatchSummary]] = []
    for ref in done:
        evidences.extend(repos.places.evidence_for_video(ref.video_id, ref.analysis_version))
        summary = _summary(repos, ref)
        if summary is not None:
            summaries.append((ref, summary))

    aggregates = aggregate_places(evidences, refs)
    place_ids = [a.place_id for a in aggregates]
    stored = repos.places.get_places(place_ids)
    names_by_place: dict[str, list[tuple[str, str]]] = defaultdict(list)
    categories: dict[str, Category] = {}
    for ref, summary in summaries:
        for c in summary.confirmed:
            names_by_place[c.place_id].append((ref.channel_id, c.name))
            categories.setdefault(c.place_id, c.category)
    for pid, item in stored.items():
        categories[pid] = item.category_from_video

    ranked = rank_places(aggregates, categories=categories, styles=job.request.styles)
    coords = repos.coords.get_many([r.place_id for r in ranked], now=int(now.timestamp()))
    # TODO(decision 0004-4): 좌표가 만료된 장소는 지도 결과에서 빼고 순위를 다시 매긴다
    pinned = [r for r in ranked if r.place_id in coords]
    areas = area_groups(
        [(r.place_id, coords[r.place_id].lat, coords[r.place_id].lng) for r in pinned]
    )
    by_id = {a.place_id: a for a in aggregates}

    places: list[ResultPlace] = []
    for rank, r in enumerate(pinned, start=1):
        agg = by_id[r.place_id]
        name = choose_display_name(names_by_place[r.place_id]) or (
            stored[r.place_id].extracted_name if r.place_id in stored else r.place_id
        )
        places.append(
            ResultPlace(
                place_id=r.place_id,
                name=name,
                category=categories.get(r.place_id, "OTHER"),
                lat=coords[r.place_id].lat,
                lng=coords[r.place_id].lng,
                area_group=areas[r.place_id],
                rank=rank,
                match_status="CONFIRMED",
                channels={"visited": agg.channels_visited, "denominator": agg.denominator},
                ratings=agg.ratings,
                time_evidence=agg.time_evidence,
                evidence=[
                    EvidenceLink(
                        channel_id=e.channel_id,
                        video_id=e.video_id,
                        start_sec=e.video_time_range.start_sec,
                        text=e.evidence_text,
                    )
                    for e in agg.evidence
                ],
            )
        )

    result = JobResult(
        job_id=job_id,
        destination=job.request.destination,
        analyzed_channels=len(successful_channels(refs)),
        failed_videos=sum(r.state == "FAILED" for r in refs),
        places=places,
        unconfirmed=_unconfirmed([s for _, s in summaries]),
    )
    key = repos.blobs.put_model(result_key(job_id), result)
    status = job_status(refs)
    elapsed = max(0, int((now - job.created_at).total_seconds()))

    def finish(j: JobItem) -> JobItem:
        metrics = j.metrics.model_copy(update={"elapsed_sec": elapsed})
        return j.model_copy(update={"status": status, "result_s3_key": key, "metrics": metrics})

    repos.jobs.mutate(job_id, finish, deps.clock())
    return AggregateOutput(job_id=job.job_id, status=status, result_s3_key=key)


def run(event: AggregateInput, deps: Deps) -> ReplaceOutput | AggregateOutput:
    if event.action == "replace":
        return replace(str(event.job_id), deps)
    return aggregate(str(event.job_id), deps)


@lru_cache(maxsize=1)
def _deps() -> Deps:
    settings = Settings.from_env()
    return Deps(settings=settings, repos=Repos.from_settings(settings))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run(AggregateInput.model_validate(event), _deps()).model_dump(mode="json")

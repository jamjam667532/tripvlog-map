"""[2-4] match: 해석 후보를 Places Text Search 결과와 규칙으로 맞춘다 (spec §5.4).

- Places 응답은 메모리에서만 쓴다. Bedrock에 넘기지 않고,
  로그·S3·DynamoDB에 이름·주소를 남기지 않는다.
- CONFIRMED: PLACE(영상 표기)·EVID 근거 아이템, 좌표는 CoordCache(25일)
- UNCONFIRMED·버린 후보: 영상별 매칭 요약(S3 match.json, 결정 0004-3)에만
- 끝나면 VideoAnalysis DONE, Jobs 영상 DONE
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from shared.clients.places import PlacesClient, PlacesTextSearch
from shared.clients.secrets import get_secret
from shared.repos import Repos, analysis_key, with_metrics, with_ref_state
from shared.rules.evidence import display_name, evidence_span
from shared.rules.matching import match_candidate
from shared.schemas.events import InterpretOutput, MatchOutput
from shared.schemas.interpretation import InterpretationResult, PlaceCandidate
from shared.schemas.items import JobItem, PlaceEvidenceItem, PlaceItem
from shared.schemas.match import ConfirmedMatch, MatchSummary, UnconfirmedMatch
from shared.schemas.observation import ObservationResult
from shared.settings import Settings

FALLBACK_QUERIES = 2


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    places: PlacesClient
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def search_queries(candidate: PlaceCandidate) -> list[str]:
    """검색어가 없으면 영상에 나온 표기로 검색한다(결정 0004-7)."""
    return list(candidate.search_queries) or list(candidate.names[:FALLBACK_QUERIES])


def _evidence(
    event: InterpretOutput, place_id: str, cand: PlaceCandidate, obs: ObservationResult
) -> PlaceEvidenceItem:
    span = evidence_span(obs.clues, cand.clue_refs)
    version = event.analysis_version
    return PlaceEvidenceItem(
        place_id=place_id,
        sk=PlaceEvidenceItem.make_sk(event.channel_id, event.video_id, version, span.start_sec),
        video_id=event.video_id,
        channel_id=event.channel_id,
        analysis_version=version,
        evidence_key=PlaceEvidenceItem.make_evidence_key(place_id, version, span.start_sec),
        visit_status=cand.visit_status,
        match_status="CONFIRMED",
        video_time_range={"start_sec": span.start_sec, "end_sec": span.end_sec},
        clue_types=span.clue_types,
        ratings=cand.ratings,
        evidence_text=span.text,
        visit_time_evidence=cand.time_evidence,
    )


def run(event: InterpretOutput, deps: Deps) -> MatchOutput:
    s, repos = deps.settings, deps.repos
    job_id, video_id, version = str(event.job_id), event.video_id, event.analysis_version
    job = repos.jobs.require(job_id)
    destination = job.request.destination
    observation = repos.blobs.get_model(event.observation_s3_key, ObservationResult)
    interpretation = repos.blobs.get_model(event.interpretation_s3_key, InterpretationResult)
    now = deps.clock()
    now_epoch = int(now.timestamp())
    calls_before = int(getattr(deps.places, "calls", 0))

    bias = deps.places.locate(destination)
    repos.places.delete_evidence_for_video(video_id, version)  # 재분석이면 이전 근거를 지운다
    confirmed: dict[str, ConfirmedMatch] = {}
    unconfirmed: list[UnconfirmedMatch] = []
    discarded = 0
    for cand in interpretation.candidates:
        hits = deps.places.search_candidate(search_queries(cand), bias=bias)
        outcome = match_candidate(cand.names, cand.branch_hint, hits)
        if outcome.status == "DISCARDED":
            discarded += 1
            continue
        if outcome.status == "UNCONFIRMED":
            unconfirmed.append(
                UnconfirmedMatch(names=cand.names, place_ids=list(outcome.place_ids))
            )
            continue
        place_id = outcome.place_ids[0]
        hit = next(h for h in hits if h.place_id == place_id)
        repos.coords.put(place_id, hit.location, now=now_epoch, ttl_days=s.coord_ttl_days)
        repos.places.put_place_if_absent(
            PlaceItem(
                place_id=place_id,
                destination=destination,
                extracted_name=cand.names[0],
                aliases=cand.names[1:],
                category_from_video=cand.category,
            )
        )
        repos.places.put_evidence(_evidence(event, place_id, cand, observation))
        confirmed.setdefault(
            place_id,
            ConfirmedMatch(
                place_id=place_id,
                name=display_name(cand.names, cand.branch_hint),
                category=cand.category,
            ),
        )

    repos.blobs.put_model(
        analysis_key(video_id, version, "match"),
        MatchSummary(
            video_id=video_id,
            analysis_version=version,
            confirmed=list(confirmed.values()),
            unconfirmed=unconfirmed,
            discarded=discarded,
        ),
    )
    repos.video_analysis.mark_done(video_id, version, job_id=job_id, now=now)
    calls = int(getattr(deps.places, "calls", 0)) - calls_before

    def record(j: JobItem) -> JobItem:
        return with_metrics(with_ref_state(j, video_id, "DONE"), places_calls=calls)

    repos.jobs.mutate(job_id, record, now)
    return MatchOutput(**event.task_fields())


@lru_cache(maxsize=1)
def _deps() -> Deps:
    s = Settings.from_env()
    return Deps(
        settings=s,
        repos=Repos.from_settings(s),
        places=PlacesTextSearch(get_secret(s.places_key_param)),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run(InterpretOutput.model_validate(event), _deps()).model_dump(mode="json")

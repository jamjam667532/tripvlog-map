"""M4 완료 조건: fixture 영상 2개로 end-to-end 결과 JSON 생성.

POST /public/jobs → (Step Functions 흉내) collect → claim·observe·interpret·match → aggregate
→ GET /public/jobs/{jobId}. DynamoDB(Local 또는 moto)와 moto S3, 외부 API는 전부 가짜.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest

from functions.aggregate import handler as aggregate_fn
from functions.api_public import handler as api
from functions.claim import handler as claim_fn
from functions.collect import handler as collect_fn
from functions.interpret import handler as interpret_fn
from functions.match import handler as match_fn
from functions.observe import handler as observe_fn
from shared.repos import Repos
from shared.schemas.api import GetJobResponse
from shared.schemas.interpretation import InterpretationResult
from shared.schemas.observation import ObservationResult
from shared.schemas.places import GeoPoint, PlaceHit
from shared.schemas.youtube import VideoMeta
from shared.settings import Settings
from tests.fakes import FakeBedrock, FakeGemini, FakePlaces, FakeStarter, FakeYouTube
from tests.integration.factories import (
    NOW,
    V1,
    V2,
    osaka_interpretation,
    osaka_observation,
    second_video,
)
from tests.integration.pipeline import Pipeline

V3, V4 = "vlog3xxxxxx", "vlog4spare0"
OSAKA = GeoPoint(lat=34.69, lng=135.50)
ICHIRAN = PlaceHit(
    place_id="ChIJ_ichiran",
    name="이치란 도톤보리점",
    address="오사카시 주오구 도톤보리 1-4",
    location=GeoPoint(lat=34.6687, lng=135.5013),
)


def meta(vid: str, channel: str, minutes: int) -> VideoMeta:
    return VideoMeta(
        video_id=vid,
        channel_id=channel,
        title="오사카 맛집 브이로그",
        description="",
        duration_sec=minutes * 60,
        privacy_status="public",
        published_at=NOW - timedelta(days=60),
    )


@dataclass
class World:
    youtube: FakeYouTube
    gemini: FakeGemini
    bedrock: FakeBedrock
    places: FakePlaces
    starter: FakeStarter


def make_world(
    search_ids: list[str],
    analyses: dict[str, tuple[ObservationResult, InterpretationResult]],
    *,
    channels: dict[str, str] | None = None,
) -> World:
    channels = channels or {}
    metas = [meta(v, channels.get(v, f"ch-{v}"), 10 + i) for i, v in enumerate(search_ids)]
    return World(
        youtube=FakeYouTube({"오사카 브이로그": search_ids}, metas),
        gemini=FakeGemini({v: obs for v, (obs, _) in analyses.items()}),
        bedrock=FakeBedrock({v: interp for v, (_, interp) in analyses.items()}),
        places=FakePlaces(
            {"一蘭 道頓堀店": [ICHIRAN], "이치란 도톤보리": [ICHIRAN]}, cities={"오사카": OSAKA}
        ),
        starter=FakeStarter(),
    )


def pipeline(repos: Repos, settings: Settings, w: World) -> Pipeline:
    def clock() -> Any:
        return NOW

    return Pipeline(
        collect=collect_fn.Deps(settings, repos, w.youtube, clock),
        claim=claim_fn.Deps(settings, repos, clock),
        observe=observe_fn.Deps(settings, repos, w.gemini, clock),
        interpret=interpret_fn.Deps(settings, repos, w.bedrock, clock),
        match=match_fn.Deps(settings, repos, w.places, clock),
        aggregate=aggregate_fn.Deps(settings, repos, clock),
    )


def submit(repos: Repos, settings: Settings, w: World) -> tuple[api.Deps, str, str]:
    deps = api.Deps(settings=settings, repos=repos, starter=w.starter, clock=lambda: NOW)
    body = {"requestId": str(uuid.uuid4()), "destination": "오사카", "styles": ["맛집"]}
    resp = api.run({"routeKey": "POST /public/jobs", "body": json.dumps(body)}, deps)
    assert resp["statusCode"] == 202
    created = json.loads(resp["body"])
    return deps, created["jobId"], created["guestAccessToken"]


def fetch(deps: api.Deps, job_id: str, token: str) -> dict[str, Any]:
    resp = api.run(
        {
            "routeKey": "GET /public/jobs/{jobId}",
            "pathParameters": {"jobId": job_id},
            "headers": {"x-guest-access-token": token},
        },
        deps,
    )
    assert resp["statusCode"] == 200
    body: dict[str, Any] = json.loads(resp["body"])
    GetJobResponse.model_validate(body)  # API 계약
    return body


@pytest.fixture
def two_videos() -> dict[str, tuple[ObservationResult, InterpretationResult]]:
    return {V1: (osaka_observation(), osaka_interpretation()), V2: second_video()}


def test_two_fixture_videos_end_to_end(
    repos: Repos, settings: Settings, two_videos: dict[str, Any]
) -> None:
    w = make_world([V1, V2], two_videos)
    deps, job_id, token = submit(repos, settings, w)
    assert w.starter.started == [job_id]

    done = pipeline(repos, settings, w).run(job_id)

    assert done.status == "SUCCEEDED"
    body = fetch(deps, job_id, token)
    assert body["status"] == "SUCCEEDED"
    assert body["progress"] == {"total": 2, "analyzed": 2, "failed": 0}
    result = body["result"]
    assert (result["destination"], result["analyzedChannels"], result["failedVideos"]) == (
        "오사카",
        2,
        0,
    )
    [ichiran] = result["places"]
    assert ichiran["placeId"] == "ChIJ_ichiran"
    assert ichiran["name"] == "이치란 · 도톤보리"  # 영상 기반 표기, Google 이름 아님
    assert (ichiran["rank"], ichiran["matchStatus"], ichiran["category"]) == (
        1,
        "CONFIRMED",
        "RESTAURANT",
    )
    assert (ichiran["lat"], ichiran["lng"]) == (34.6687, 135.5013)
    assert ichiran["channels"] == {"visited": 2, "denominator": 2}
    assert ichiran["ratings"]["taste"] == {"positive": 2, "negative": 0, "mixed": 0}
    assert ichiran["ratings"]["wait"] == {"positive": 1, "negative": 1, "mixed": 0}
    assert {(t["kind"], t["situation"]) for t in ichiran["timeEvidence"]} == {
        ("WAIT_EXPERIENCE", "OPENING"),
        ("WAIT_EXPERIENCE", "LUNCH_PEAK"),
    }
    assert not any(t["recommend"] for t in ichiran["timeEvidence"])  # 짧은 대기 1채널뿐
    assert [(e["videoId"], e["startSec"]) for e in ichiran["evidence"]] == [(V1, 750), (V2, 300)]
    assert ichiran["areaGroup"] == "지역 1"
    assert result["unconfirmed"] == []
    assert "이치란 도톤보리점" not in json.dumps(result, ensure_ascii=False)

    job = repos.jobs.require(job_id)
    assert job.metrics.gemini_tokens == 2 * FakeGemini.TOKENS_PER_CALL
    assert job.metrics.places_calls == w.places.calls
    assert w.gemini.calls == {V1: 1, V2: 1}


def test_failed_video_without_spare_is_partial(
    repos: Repos, settings: Settings, two_videos: dict[str, Any]
) -> None:
    w = make_world([V1, V2, V3], two_videos)  # V3는 Gemini 관찰 실패
    deps, job_id, token = submit(repos, settings, w)

    assert pipeline(repos, settings, w).run(job_id).status == "PARTIAL"

    body = fetch(deps, job_id, token)
    assert body["progress"] == {"total": 3, "analyzed": 2, "failed": 1}
    assert {v["videoId"]: v["state"] for v in body["videos"]}[V3] == "FAILED"
    assert (body["result"]["analyzedChannels"], body["result"]["failedVideos"]) == (2, 1)
    # 실패 채널은 분모에서 빠진다
    assert body["result"]["places"][0]["channels"] == {"visited": 2, "denominator": 2}
    assert w.bedrock.calls == {V1: 1, V2: 1}


def test_failed_video_is_replaced_by_spare(
    repos: Repos, settings: Settings, two_videos: dict[str, Any]
) -> None:
    analyses = {**two_videos, V4: second_video(V4)}
    ids = [V1, V2, V3, "vlog5xxxxxx", "vlog6xxxxxx", V4]
    w = make_world(ids, analyses)
    # 5개 중 3개(V3, vlog5, vlog6)는 관찰 실패. 예비는 V4 하나
    deps, job_id, token = submit(repos, settings, w)

    run = pipeline(repos, settings, w)
    assert run.run(job_id).status == "PARTIAL"  # 대체는 1개뿐 → 실패 2개는 남는다

    job = repos.jobs.require(job_id)
    replacement = next(r for r in job.video_refs if r.replaces is not None)
    assert (replacement.video_id, replacement.replaces, replacement.state) == (V4, V3, "DONE")
    assert job.spare_videos == []
    body = fetch(deps, job_id, token)
    assert body["result"]["places"][0]["channels"] == {"visited": 3, "denominator": 3}


def test_second_job_reuses_analysis_without_ai_calls(
    repos: Repos, settings: Settings, two_videos: dict[str, Any]
) -> None:
    w = make_world([V1, V2], two_videos)
    _, first, _ = submit(repos, settings, w)
    pipeline(repos, settings, w).run(first)
    deps, second, token = submit(repos, settings, w)

    run = pipeline(repos, settings, w)
    assert run.run(second).status == "SUCCEEDED"

    assert w.gemini.calls == {V1: 1, V2: 1}
    assert w.bedrock.calls == {V1: 1, V2: 1}
    assert [s for s in run.steps if not s.startswith("claim")] == []  # 전부 REUSE
    assert fetch(deps, second, token)["result"]["places"][0]["channels"]["visited"] == 2

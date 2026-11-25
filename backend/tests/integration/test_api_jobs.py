"""[M8] api_jobs: 로그인 사용자의 작업 (spec §3.3, 결정 0010). 실행 시작은 가짜."""

import json
import uuid
from typing import Any

import pytest

from functions.aggregate.handler import Deps as AggDeps
from functions.aggregate.handler import run as aggregate
from functions.api_jobs.handler import Deps, run
from functions.job_api import job_id_for
from shared.repos import Repos, with_refs
from shared.schemas.events import AggregateInput
from shared.schemas.items import PlaceItem, UserItem, UserPreferences, VideoRef
from shared.schemas.places import GeoPoint
from shared.settings import Settings
from tests.fakes import FakeStarter
from tests.integration.factories import NOW, NOW_EPOCH, VERSION
from tests.unit.rules.factories import evidence

SUB = "sub-123"
USER = "google:" + SUB


@pytest.fixture
def starter() -> FakeStarter:
    return FakeStarter()


@pytest.fixture
def deps(repos: Repos, settings: Settings, starter: FakeStarter) -> Deps:
    return Deps(settings=settings, repos=repos, starter=starter, clock=lambda: NOW)


def call(
    deps: Deps, route: str, *, body: Any = None, job_id: str | None = None, sub: str | None = SUB
) -> tuple[int, dict[str, Any]]:
    ev: dict[str, Any] = {"routeKey": route, "headers": {}}
    if sub is not None:
        ev["requestContext"] = {"authorizer": {"jwt": {"claims": {"sub": sub}}}}
    if body is not None:
        ev["body"] = json.dumps(body, ensure_ascii=False)
    if job_id is not None:
        ev["pathParameters"] = {"jobId": job_id}
    resp = run(ev, deps)
    return resp["statusCode"], json.loads(resp["body"])


def new_request(**kw: Any) -> dict[str, Any]:
    return {"requestId": str(uuid.uuid4()), "destination": "오사카", **kw}


def test_create_job_belongs_to_jwt_user_without_guest_token(
    deps: Deps, repos: Repos, starter: FakeStarter
) -> None:
    req = new_request(styles=["맛집"])
    status, body = call(deps, "POST /jobs", body=req)
    assert status == 202 and body["status"] == "QUEUED"
    assert "guestAccessToken" not in body
    job = repos.jobs.require(body["jobId"])
    assert job.user_id == USER and job.guest_access_hash is None
    assert body["jobId"] == str(job_id_for(uuid.UUID(req["requestId"])))
    assert job.execution_arn is not None


def test_create_job_needs_login_and_rejects_user_id_in_body(deps: Deps) -> None:
    assert call(deps, "POST /jobs", body=new_request(), sub=None)[0] == 401
    assert call(deps, "POST /jobs", body=new_request(userId="google:attacker"))[0] == 400


def test_empty_styles_fall_back_to_saved_preferences(deps: Deps, repos: Repos) -> None:
    repos.users.put(
        UserItem(
            user_id=USER, preferences=UserPreferences(styles=["카페·포토스팟"], companion="친구")
        )
    )
    _, body = call(deps, "POST /jobs", body=new_request())
    job = repos.jobs.require(body["jobId"])
    assert (job.request.styles, job.request.companion) == (["카페·포토스팟"], "친구")

    _, body = call(deps, "POST /jobs", body=new_request(styles=["맛집"]))
    assert repos.jobs.require(body["jobId"]).request.styles == ["맛집"]  # 요청 값이 우선


def test_duplicate_request_is_409(deps: Deps) -> None:
    req = new_request()
    assert call(deps, "POST /jobs", body=req)[0] == 202
    assert call(deps, "POST /jobs", body=req)[0] == 409


def test_only_owner_can_read_job(deps: Deps) -> None:
    _, body = call(deps, "POST /jobs", body=new_request())
    job_id = body["jobId"]
    assert call(deps, "GET /jobs/{jobId}", job_id=job_id)[0] == 200
    assert call(deps, "GET /jobs/{jobId}", job_id=job_id, sub="someone-else")[0] == 404
    assert call(deps, "GET /jobs/{jobId}", job_id="not-a-uuid")[0] == 404


def test_guest_job_is_not_visible_on_login_path(deps: Deps, repos: Repos) -> None:
    from tests.integration.factories import guest_job

    job = guest_job()
    repos.jobs.create(job)
    assert call(deps, "GET /jobs/{jobId}", job_id=str(job.job_id))[0] == 404


def _finished_job(deps: Deps, repos: Repos, settings: Settings) -> str:
    """맛집 스타일로 끝난 작업: 식당 P_r(c1)이 카페 P_c(c2)보다 위."""
    _, body = call(deps, "POST /jobs", body=new_request(styles=["맛집"]))
    job_id = str(body["jobId"])
    refs = [
        VideoRef(video_id="v1", channel_id="c1", analysis_version=VERSION, state="DONE"),
        VideoRef(video_id="v2", channel_id="c2", analysis_version=VERSION, state="DONE"),
    ]
    repos.jobs.mutate(job_id, lambda j: with_refs(j, refs), NOW)
    for pid, cat, ch, vid in [("P_r", "RESTAURANT", "c1", "v1"), ("P_c", "CAFE", "c2", "v2")]:
        repos.places.put_place_if_absent(
            PlaceItem.model_validate(
                {
                    "placeId": pid,
                    "destination": "오사카",
                    "extractedName": pid,
                    "categoryFromVideo": cat,
                }
            )
        )
        repos.coords.put(pid, GeoPoint(lat=34.66, lng=135.5), now=NOW_EPOCH, ttl_days=25)
        repos.places.put_evidence(evidence(pid, ch, vid, 10))
    aggregate(
        AggregateInput.model_validate({"jobId": job_id}),
        AggDeps(settings=settings, repos=repos, clock=lambda: NOW),
    )
    return job_id


def test_rerank_recomputes_order_without_saving(
    deps: Deps, repos: Repos, settings: Settings
) -> None:
    job_id = _finished_job(deps, repos, settings)
    _, before = call(deps, "GET /jobs/{jobId}", job_id=job_id)
    assert [p["placeId"] for p in before["result"]["places"]] == ["P_r", "P_c"]

    status, body = call(
        deps, "POST /jobs/{jobId}/rerank", job_id=job_id, body={"styles": ["카페·포토스팟"]}
    )
    assert status == 200 and body["resultStage"] == "FINAL"
    assert [p["placeId"] for p in body["result"]["places"]] == ["P_c", "P_r"]

    _, after = call(deps, "GET /jobs/{jobId}", job_id=job_id)
    assert [p["placeId"] for p in after["result"]["places"]] == ["P_r", "P_c"]  # 저장 안 함


def test_rerank_rules(deps: Deps) -> None:
    _, body = call(deps, "POST /jobs", body=new_request())
    job_id = body["jobId"]
    route = "POST /jobs/{jobId}/rerank"
    assert call(deps, route, job_id=job_id, body={"styles": ["맛집"]})[0] == 409  # 아직 분석 중
    assert call(deps, route, job_id=job_id, body={}, sub="someone-else")[0] == 404

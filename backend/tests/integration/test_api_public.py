"""api_public: 작업 접수(requestId 중복 409, 토큰 해시 저장)와 조회(토큰 불일치 404)."""

import json
import uuid
from typing import Any

import pytest

from functions.api_public.handler import Deps, hash_token, job_id_for, run
from shared.repos import Repos, result_key, with_refs
from shared.schemas.items import VideoRef
from shared.schemas.result import JobResult
from shared.settings import Settings
from tests.fakes import FakeStarter
from tests.integration.factories import NOW, VERSION


@pytest.fixture
def starter() -> FakeStarter:
    return FakeStarter()


@pytest.fixture
def deps(repos: Repos, settings: Settings, starter: FakeStarter) -> Deps:
    return Deps(settings=settings, repos=repos, starter=starter, clock=lambda: NOW)


def post(deps: Deps, body: Any) -> tuple[int, dict[str, Any]]:
    raw = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    resp = run({"routeKey": "POST /public/jobs", "body": raw}, deps)
    return resp["statusCode"], json.loads(resp["body"])


def get(deps: Deps, job_id: str, token: str | None) -> tuple[int, dict[str, Any]]:
    headers = {} if token is None else {"x-guest-access-token": token}
    resp = run(
        {
            "routeKey": "GET /public/jobs/{jobId}",
            "pathParameters": {"jobId": job_id},
            "headers": headers,
        },
        deps,
    )
    assert resp["headers"]["cache-control"] == "no-store"
    return resp["statusCode"], json.loads(resp["body"])


def new_request(**kw: Any) -> dict[str, Any]:
    return {"requestId": str(uuid.uuid4()), "destination": "오사카", "styles": ["맛집"], **kw}


def test_create_job_returns_token_once_and_stores_only_hash(
    deps: Deps, repos: Repos, starter: FakeStarter, aws: tuple[Any, Any], settings: Settings
) -> None:
    req = new_request(companion="커플")
    status, body = post(deps, req)

    assert status == 202
    assert body["status"] == "QUEUED"
    token, job_id = body["guestAccessToken"], body["jobId"]
    assert len(token) == 43
    assert job_id == str(job_id_for(uuid.UUID(req["requestId"])))
    assert uuid.UUID(job_id).version == 4
    assert starter.started == [job_id]

    job = repos.jobs.require(job_id)
    assert job.guest_access_hash == hash_token(token)
    assert job.execution_arn == FakeStarter.ARN_PREFIX + job_id
    assert (job.request.destination, job.request.companion) == ("오사카", "커플")
    dynamodb, _ = aws
    raw = json.dumps(dynamodb.Table(settings.jobs_table).scan()["Items"], default=str)
    assert token not in raw


def test_duplicate_request_id_returns_409_with_job_id(deps: Deps, starter: FakeStarter) -> None:
    req = new_request()
    _, first = post(deps, req)
    status, body = post(deps, {**req, "destination": "교토"})
    assert status == 409
    assert body == {
        "error": {"code": "DUPLICATE_REQUEST", "message": "request already accepted"},
        "jobId": first["jobId"],
    }
    assert "guestAccessToken" not in body
    assert len(starter.started) == 1


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        {"destination": "오사카"},
        new_request(userId="someone"),  # 요청 본문의 userId는 받지 않는다
        new_request(days=3),  # 기간 입력 없음
        new_request(styles=["맛집", "맛집"]),
    ],
)
def test_invalid_body_is_400(deps: Deps, starter: FakeStarter, body: Any) -> None:
    status, resp = post(deps, body)
    assert (status, resp["error"]["code"]) == (400, "INVALID_REQUEST")
    assert starter.started == []


def test_start_failure_marks_job_failed(repos: Repos, settings: Settings) -> None:
    deps = Deps(settings=settings, repos=repos, starter=FakeStarter(fail=True), clock=lambda: NOW)
    req = new_request()
    status, body = post(deps, req)
    assert (status, body["error"]["code"]) == (503, "START_FAILED")
    assert repos.jobs.require(str(job_id_for(uuid.UUID(req["requestId"])))).status == "FAILED"


def test_get_job_with_token_shows_progress(deps: Deps, repos: Repos) -> None:
    _, created = post(deps, new_request())
    job_id, token = created["jobId"], created["guestAccessToken"]
    refs = [
        VideoRef(video_id="v1", channel_id="c1", analysis_version=VERSION, state="DONE"),
        VideoRef(video_id="v2", channel_id="c2", analysis_version=VERSION, state="ANALYZING"),
    ]
    repos.jobs.mutate(
        job_id, lambda j: with_refs(j, refs).model_copy(update={"status": "RUNNING"}), NOW
    )

    status, body = get(deps, job_id, token)
    assert status == 200
    assert body["status"] == "RUNNING"
    assert body["progress"] == {"total": 2, "analyzed": 1, "failed": 0}
    assert body["videos"] == [
        {"videoId": "v1", "state": "DONE"},
        {"videoId": "v2", "state": "ANALYZING"},
    ]
    assert "result" not in body  # 진행 중에는 결과 없음


def test_get_finished_job_returns_result_from_s3(deps: Deps, repos: Repos) -> None:
    _, created = post(deps, new_request())
    job_id, token = created["jobId"], created["guestAccessToken"]
    result = JobResult(job_id=job_id, destination="오사카", analyzed_channels=0, failed_videos=0)
    key = repos.blobs.put_model(result_key(job_id), result)
    repos.jobs.mutate(
        job_id,
        lambda j: j.model_copy(update={"status": "SUCCEEDED", "result_s3_key": key}),
        NOW,
    )
    status, body = get(deps, job_id, token)
    assert status == 200
    assert body["result"]["destination"] == "오사카"
    assert "results/" not in json.dumps(body)  # S3 키를 노출하지 않는다


def test_wrong_missing_token_and_unknown_job_look_the_same(deps: Deps) -> None:
    _, created = post(deps, new_request())
    job_id, token = created["jobId"], created["guestAccessToken"]
    other_token = token[:-1] + ("A" if token[-1] != "A" else "B")
    responses = [
        get(deps, job_id, other_token),
        get(deps, job_id, None),
        get(deps, job_id, ""),
        get(deps, str(uuid.uuid4()), token),
        get(deps, "not-a-uuid", token),
    ]
    assert all(
        r == (404, {"error": {"code": "NOT_FOUND", "message": "job not found"}}) for r in responses
    )


def test_unknown_route_is_404(deps: Deps) -> None:
    resp = run({"routeKey": "DELETE /public/jobs/{jobId}"}, deps)
    assert resp["statusCode"] == 404

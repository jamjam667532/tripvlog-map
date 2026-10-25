"""aggregate action=snapshot: 진행 중에도 끝난 영상만으로 결과를 보여 준다."""

from typing import Any

from functions.aggregate import handler as aggregate_fn
from functions.collect import handler as collect_fn
from shared.repos import Repos
from shared.schemas.events import AggregateInput, JobInput
from shared.settings import Settings
from tests.integration.factories import (
    V1,
    V2,
    osaka_interpretation,
    osaka_observation,
    second_video,
)
from tests.integration.test_e2e_osaka import fetch, make_world, pipeline, submit


def _snapshot(job_id: str, p: Any) -> None:
    aggregate_fn.run(
        AggregateInput.model_validate({"jobId": job_id, "action": "snapshot"}), p.aggregate
    )


def test_snapshot_shows_finished_videos_while_running(repos: Repos, settings: Settings) -> None:
    w = make_world(
        [V1, V2], {V1: (osaka_observation(), osaka_interpretation()), V2: second_video()}
    )
    deps, job_id, token = submit(repos, settings, w)
    p = pipeline(repos, settings, w)

    collected = collect_fn.run(JobInput.model_validate({"jobId": job_id}), p.collect)
    refs = collected.model_dump(mode="json")["videoRefs"]

    # 결과가 아직 없으면 result·resultStage 없음
    body = fetch(deps, job_id, token)
    assert "result" not in body and "resultStage" not in body  # null은 응답에서 빠진다

    p.run_video(refs[0])
    _snapshot(job_id, p)
    body = fetch(deps, job_id, token)
    assert body["status"] == "RUNNING"
    assert body["resultStage"] == "PARTIAL_LIVE"
    live = body["result"]
    assert live["analyzedChannels"] == 1
    [ichiran] = live["places"]
    assert ichiran["channels"] == {"visited": 1, "denominator": 1}  # 지금까지 끝난 채널만 분모
    # 아직 분석 중인 영상은 건너뜀으로 바뀌지 않는다
    assert {v["videoId"]: v["state"] for v in body["videos"]}[V2] != "SKIPPED"

    p.run_video(refs[1])
    aggregate_fn.run(AggregateInput.model_validate({"jobId": job_id}), p.aggregate)
    body = fetch(deps, job_id, token)
    assert body["status"] == "SUCCEEDED"
    assert body["resultStage"] == "FINAL"
    assert body["result"]["places"][0]["channels"] == {"visited": 2, "denominator": 2}

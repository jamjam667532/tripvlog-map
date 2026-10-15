"""claim·observe·interpret 핸들러: 선점·재사용·대기, 관찰·해석 S3 저장, 실패 기록."""

from dataclasses import replace

import pytest

from functions.claim import handler as claim_fn
from functions.interpret import handler as interpret_fn
from functions.observe import handler as observe_fn
from shared.clients.errors import InvalidModelOutput
from shared.repos import Repos, with_refs
from shared.schemas.events import ClaimOutput, FailOutput, VideoTask
from shared.schemas.interpretation import InterpretationResult
from shared.schemas.items import JobItem, VideoRef
from shared.schemas.observation import ObservationResult
from shared.settings import Settings
from tests.fakes import FakeBedrock, FakeGemini
from tests.integration.factories import (
    NOW,
    V1,
    VERSION,
    guest_job,
    osaka_interpretation,
    osaka_observation,
)


def _job_with_video(repos: Repos, video_id: str = V1, channel_id: str = "c1") -> JobItem:
    job = guest_job()
    repos.jobs.create(job)
    ref = VideoRef(video_id=video_id, channel_id=channel_id, analysis_version=VERSION)
    return repos.jobs.mutate(str(job.job_id), lambda j: with_refs(j, [ref]), NOW)


def _task(job: JobItem, video_id: str = V1, channel_id: str = "c1") -> VideoTask:
    return VideoTask(
        job_id=job.job_id, video_id=video_id, channel_id=channel_id, analysis_version=VERSION
    )


def _claim(job: JobItem, deps: claim_fn.Deps, wait_count: int = 0) -> ClaimOutput:
    out = claim_fn.run({**_task(job).model_dump(mode="json"), "waitCount": wait_count}, deps)
    assert isinstance(out, ClaimOutput)
    return out


@pytest.fixture
def claim_deps(repos: Repos, settings: Settings) -> claim_fn.Deps:
    return claim_fn.Deps(settings=settings, repos=repos, clock=lambda: NOW)


def _analyze(
    repos: Repos, settings: Settings, job: JobItem, gemini: FakeGemini, bedrock: FakeBedrock
) -> None:
    """observe → interpret → (match 대신) 분석 완료 기록."""
    obs = observe_fn.run(
        _task(job),
        observe_fn.Deps(settings=settings, repos=repos, gemini=gemini, clock=lambda: NOW),
    )
    interpret_fn.run(
        obs, interpret_fn.Deps(settings=settings, repos=repos, bedrock=bedrock, clock=lambda: NOW)
    )
    repos.video_analysis.mark_done(V1, VERSION, job_id=str(job.job_id), now=NOW)


def test_claim_analyze_marks_job_video_analyzing(repos: Repos, claim_deps: claim_fn.Deps) -> None:
    job = _job_with_video(repos)
    assert _claim(job, claim_deps).decision == "ANALYZE"
    assert repos.jobs.require(str(job.job_id)).video_refs[0].state == "ANALYZING"


def test_observe_and_interpret_store_s3_and_usage(repos: Repos, settings: Settings) -> None:
    job = _job_with_video(repos)
    claim_fn.run(_task(job).model_dump(mode="json"), claim_fn.Deps(settings, repos, lambda: NOW))
    gemini = FakeGemini({V1: osaka_observation()})
    bedrock = FakeBedrock({V1: osaka_interpretation()})

    obs_out = observe_fn.run(_task(job), observe_fn.Deps(settings, repos, gemini, lambda: NOW))
    assert obs_out.observation_s3_key == f"analysis/{V1}/{VERSION}/observation.json"
    assert repos.blobs.get_model(obs_out.observation_s3_key, ObservationResult) == (
        osaka_observation()
    )

    int_out = interpret_fn.run(obs_out, interpret_fn.Deps(settings, repos, bedrock, lambda: NOW))
    stored = repos.blobs.get_model(int_out.interpretation_s3_key, InterpretationResult)
    assert [c.candidate_id for c in stored.candidates] == ["c1", "c2"]

    va = repos.video_analysis.get(V1, VERSION)
    assert va is not None and va.status == "ANALYZING"
    assert va.observation_s3_key == obs_out.observation_s3_key
    assert va.interpretation_s3_key == int_out.interpretation_s3_key
    assert (va.usage.gemini_tokens, va.usage.bedrock_input_tokens) == (1000, 100)
    metrics = repos.jobs.require(str(job.job_id)).metrics
    assert (metrics.gemini_tokens, metrics.bedrock_output_tokens) == (1000, 50)


def test_same_video_two_jobs_calls_gemini_once(
    repos: Repos, settings: Settings, claim_deps: claim_fn.Deps
) -> None:
    gemini = FakeGemini({V1: osaka_observation()})
    bedrock = FakeBedrock({V1: osaka_interpretation()})
    job_a, job_b = _job_with_video(repos), _job_with_video(repos)

    assert _claim(job_a, claim_deps).decision == "ANALYZE"
    waiting = _claim(job_b, claim_deps)
    assert (waiting.decision, waiting.wait_count) == ("WAIT", 1)

    _analyze(repos, settings, job_a, gemini, bedrock)

    assert _claim(job_b, claim_deps, waiting.wait_count).decision == "REUSE"
    assert repos.jobs.require(str(job_b.job_id)).video_refs[0].state == "DONE"
    assert gemini.calls == {V1: 1}
    assert bedrock.calls == {V1: 1}


def test_claim_wait_times_out(repos: Repos, settings: Settings, claim_deps: claim_fn.Deps) -> None:
    job_a, job_b = _job_with_video(repos), _job_with_video(repos)
    _claim(job_a, claim_deps)
    deps = replace(claim_deps, settings=replace(settings, max_claim_waits=2))
    assert _claim(job_b, deps, wait_count=1).decision == "WAIT"
    with pytest.raises(claim_fn.ClaimWaitTimeout):
        _claim(job_b, deps, wait_count=2)


def test_observe_failure_then_fail_action(
    repos: Repos, settings: Settings, claim_deps: claim_fn.Deps
) -> None:
    job = _job_with_video(repos)
    _claim(job, claim_deps)
    with pytest.raises(InvalidModelOutput):
        observe_fn.run(_task(job), observe_fn.Deps(settings, repos, FakeGemini({}), lambda: NOW))

    out = claim_fn.run(
        {
            **_task(job).model_dump(mode="json"),
            "action": "fail",
            "error": {"Error": "InvalidModelOutput", "Cause": "raw model text 비밀"},
        },
        claim_deps,
    )
    assert isinstance(out, FailOutput)
    ref = repos.jobs.require(str(job.job_id)).video_refs[0]
    assert (ref.state, ref.error) == ("FAILED", "InvalidModelOutput")
    va = repos.video_analysis.get(V1, VERSION)
    assert va is not None and va.status == "FAILED"
    # 실패한 영상은 다음 작업이 다시 선점할 수 있다
    other = _job_with_video(repos)
    assert _claim(other, claim_deps).decision == "ANALYZE"


def test_fail_does_not_touch_analysis_owned_by_other_job(
    repos: Repos, claim_deps: claim_fn.Deps
) -> None:
    owner, waiter = _job_with_video(repos), _job_with_video(repos)
    _claim(owner, claim_deps)
    claim_fn.run({**_task(waiter).model_dump(mode="json"), "action": "fail"}, claim_deps)
    va = repos.video_analysis.get(V1, VERSION)
    assert va is not None and va.status == "ANALYZING" and va.lock_owner == str(owner.job_id)
    assert repos.jobs.require(str(waiter.job_id)).video_refs[0].error == "Unknown"

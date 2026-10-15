"""저장소 골격 확인. 모든 핸들러 모듈이 import되고 진입점을 갖는지 본다."""

import importlib

import pytest

FUNCTIONS = [
    "api_public",
    "api_jobs",
    "api_me",
    "collect",
    "claim",
    "observe",
    "interpret",
    "match",
    "aggregate",
    "cleanup",
]


@pytest.mark.parametrize("name", FUNCTIONS)
def test_handler_module_has_entrypoint(name: str) -> None:
    module = importlib.import_module(f"functions.{name}.handler")
    assert callable(module.handler)


def test_config_caps_videos_per_job() -> None:
    from infra import config

    assert config.MAX_VIDEOS_PER_JOB == 5

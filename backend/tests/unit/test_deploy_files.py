"""[M5] 배포 파일이 코드와 어긋나지 않는지 본다. AWS는 부르지 않는다."""

import importlib.util
import json
import stat
from pathlib import Path
from types import ModuleType

import pytest

from shared.clients import secrets
from shared.settings import Settings

ROOT = Path(__file__).resolve().parents[3]


def _make_keys() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_keys", ROOT / "scripts/make_keys_json.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENV_TEXT = """# 주석
GEMINI_API_KEY=g-value
YOUTUBE_API_KEY="y-value"
PLACES_API_KEY='p-value'
LLM_API_KEY=l-value
LLM_BASE_URL=https://gw.example/v1?a=b
OTHER=ignored
"""


def test_keys_file_uses_the_names_secrets_reads(tmp_path: Path) -> None:
    mk = _make_keys()
    env = tmp_path / ".env"
    env.write_text(ENV_TEXT)
    out = tmp_path / "keys.json"
    mk.write_keys(mk.build_keys(mk.read_env(env)), out)

    keys = json.loads(out.read_text())
    assert set(keys) == {
        secrets.SECRET_GEMINI,
        secrets.SECRET_YOUTUBE,
        secrets.SECRET_PLACES,
        secrets.SECRET_LLM_API_KEY,
        secrets.SECRET_LLM_BASE_URL,
    }
    assert keys["youtube"] == "y-value"
    assert keys["llm_base_url"] == "https://gw.example/v1?a=b"
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_missing_key_is_named_without_printing_values() -> None:
    mk = _make_keys()
    with pytest.raises(SystemExit) as e:
        mk.build_keys({"GEMINI_API_KEY": "secret-value"})
    assert "YOUTUBE_API_KEY" in str(e.value)
    assert "secret-value" not in str(e.value)


def test_lambda_env_file_configures_settings_without_secrets() -> None:
    variables = json.loads((ROOT / "infra/lambda-env.json").read_text())["Variables"]
    s = Settings.from_env(variables)
    for table in (
        s.jobs_table,
        s.users_table,
        s.youtube_cache_table,
        s.video_analysis_table,
        s.places_table,
        s.coord_cache_table,
    ):
        assert table.startswith("sgu-clicktotrip-")  # 결정 0007-4
    assert s.bucket == "sgu-clicktotrip-data"
    assert s.gemini_models
    assert s.bedrock_interpreter_model_id == "bedrock-haiku"
    assert s.dynamodb_endpoint is None
    # 결정 0007: 환경 변수에 비밀값 금지
    assert not [name for name in variables if "API_KEY" in name or "SECRET" in name]


def test_cloudshell_script_uses_the_same_env_as_lambda_env_file() -> None:
    script = (ROOT / "infra/deploy/create_functions.sh").read_text()
    line = next(x for x in script.splitlines() if x.startswith("ENV_JSON='"))
    embedded = json.loads(line.removeprefix("ENV_JSON='").removesuffix("'"))
    assert embedded == json.loads((ROOT / "infra/lambda-env.json").read_text())
    handlers = {p.parent.name for p in (ROOT / "backend/functions").glob("*/handler.py")}
    listed = {
        x.split()[0] for x in script.split("<<'LIST'\n", 1)[1].split("\nLIST", 1)[0].splitlines()
    }
    assert listed <= handlers
    assert handlers - listed == {"api_jobs", "api_me"}  # M8이라 아직 만들지 않는다

"""Lambda 설정 버킷에 올릴 keys.json을 .env에서 만든다 (결정 0007-3).

uv run python scripts/make_keys_json.py /Users/m2/y4s2prjct/experiments/.env

값은 화면에 출력하지 않는다. 결과 파일은 저장소 밖(기본 ~/sgu-clicktotrip-keys.json)에 권한 600으로
만든다. 콘솔에서 올린 뒤 지운다.
"""

import json
import os
import sys
from pathlib import Path

# keys.json 이름 ← .env 이름 (shared/clients/secrets.py의 SECRET_*)
NAMES = {
    "gemini": "GEMINI_API_KEY",
    "youtube": "YOUTUBE_API_KEY",
    "places": "PLACES_API_KEY",
    "llm_api_key": "LLM_API_KEY",
    "llm_base_url": "LLM_BASE_URL",
}


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            env[name.strip()] = value.strip().strip("'\"")
    return env


def build_keys(env: dict[str, str]) -> dict[str, str]:
    missing = [source for source in NAMES.values() if not env.get(source)]
    if missing:
        raise SystemExit(f".env에 없는 값: {', '.join(missing)}")
    return {name: env[source] for name, source in NAMES.items()}


def write_keys(keys: dict[str, str], out: Path) -> None:
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(keys, f)
    out.chmod(0o600)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "sgu-clicktotrip-keys.json"
    write_keys(build_keys(read_env(Path(sys.argv[1]))), out)
    print(f"{out} (키 {len(NAMES)}개: {', '.join(NAMES)})")


if __name__ == "__main__":
    main()

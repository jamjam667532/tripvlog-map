"""backend/shared/prompts/*.md 로더.

프롬프트는 코드와 함께 버전 관리하고, 바뀌면 ANALYSIS_VERSION을 올린다.
"""

from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()

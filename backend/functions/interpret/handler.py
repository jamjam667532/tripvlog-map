"""interpret Lambda 핸들러. 구현은 spec §11 마일스톤에서 채운다."""

from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    raise NotImplementedError("interpret")

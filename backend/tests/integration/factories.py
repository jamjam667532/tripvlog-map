"""통합 테스트용 아이템 생성 도우미."""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from shared.schemas.items import JobItem

VERSION = "v1-haiku45"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
NOW_EPOCH = int(NOW.timestamp())


def guest_job(destination: str = "오사카", **kw: Any) -> JobItem:
    data: dict[str, Any] = {
        "jobId": str(uuid.uuid4()),
        "requestId": str(uuid.uuid4()),
        "guestAccessHash": hashlib.sha256(b"token").hexdigest(),
        "status": "QUEUED",
        "request": {"destination": destination, "styles": ["맛집"], "companion": None},
        "createdAt": NOW.isoformat(),
        "updatedAt": NOW.isoformat(),
        **kw,
    }
    return JobItem.model_validate(data)

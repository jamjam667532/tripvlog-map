"""통합 테스트용 아이템 생성 도우미."""

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.schemas.interpretation import InterpretationResult
from shared.schemas.items import JobItem
from shared.schemas.observation import ObservationResult

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


# ---------- 관찰·해석 fixture ----------

CONTRACTS = Path(__file__).parent.parent / "fixtures" / "contracts"
V1 = "dQw4w9WgXcQ"  # contracts/observation/valid_osaka.json 영상


def osaka_observation() -> ObservationResult:
    return ObservationResult.model_validate_json(
        (CONTRACTS / "observation" / "valid_osaka.json").read_text(encoding="utf-8")
    )


def osaka_interpretation() -> InterpretationResult:
    return InterpretationResult.model_validate_json(
        (CONTRACTS / "interpretation" / "valid_osaka.json").read_text(encoding="utf-8")
    )


V2 = "vlog2xxxxxx"


def second_video(video_id: str = V2) -> tuple[ObservationResult, InterpretationResult]:
    """두 번째 채널의 이치란 방문: 오픈 직후 대기 짧음, 맛 긍정."""
    obs = ObservationResult.model_validate(
        {
            "video_id": video_id,
            "clues": [
                {
                    "start_sec": 300,
                    "end_sec": 420,
                    "clue_type": "SPEECH",
                    "heard_name": "이치란",
                    "utterance": "오픈 직후라 줄 거의 없었어요. 맛있다!",
                },
            ],
        }
    )
    interp = InterpretationResult.model_validate(
        {
            "video_id": video_id,
            "analysis_version": VERSION,
            "candidates": [
                {
                    "candidate_id": "c1",
                    "names": ["이치란"],
                    "branch_hint": "도톤보리",
                    "search_queries": ["이치란 도톤보리"],
                    "category": "RESTAURANT",
                    "visit_status": "VISITED",
                    "clue_refs": [0],
                    "ratings": {"overall": "POSITIVE", "taste": "POSITIVE", "wait": "POSITIVE"},
                    "time_evidence": [
                        {
                            "kind": "WAIT_EXPERIENCE",
                            "situation": "OPENING",
                            "evidence_text": "오픈 직후라 줄 거의 없었어요",
                        }
                    ],
                },
            ],
        }
    )
    return obs, interp

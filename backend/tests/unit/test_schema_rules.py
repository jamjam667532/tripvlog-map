"""명세가 정한 스키마 단계의 변환·검증 규칙 (spec §3, §4, §5.3)."""

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from shared.schemas.api import CreateJobRequest, ErrorResponse, UpdatePreferencesRequest
from shared.schemas.common import Ratings, TimeEvidence
from shared.schemas.interpretation import InterpretationResult, link_to_observation
from shared.schemas.items import CoordCacheItem, JobItem, PlaceEvidenceItem, VideoRef
from shared.schemas.observation import ObservationResult
from shared.schemas.result import EvidenceLink


def _candidate(**overrides: Any) -> dict[str, Any]:
    return {
        "candidate_id": "c1",
        "names": ["이치란"],
        "category": "RESTAURANT",
        "visit_status": "VISITED",
        "clue_refs": [0],
        **overrides,
    }


def _interpretation(*candidates: dict[str, Any]) -> InterpretationResult:
    return InterpretationResult.model_validate(
        {"video_id": "abc", "analysis_version": "v1-haiku45", "candidates": list(candidates)}
    )


# ---------- 시간 근거 (spec §5.3, §8 필수 케이스) ----------


@pytest.mark.parametrize(
    ("kind", "situation"),
    [("SCENE", "NIGHT"), ("WAIT_EXPERIENCE", "MORNING"), ("CREATOR_TIP", "OPENING")],
)
def test_local_clock_time_forced_null_unless_stated_time(kind: str, situation: str) -> None:
    ev = TimeEvidence.model_validate(
        {"kind": kind, "situation": situation, "localClockTime": "09:00", "evidenceText": "x"}
    )
    assert ev.local_clock_time is None


def test_local_clock_time_dropped_even_if_malformed_for_other_kinds() -> None:
    ev = TimeEvidence.model_validate(
        {"kind": "SCENE", "situation": "NIGHT", "local_clock_time": "밤", "evidence_text": "x"}
    )
    assert ev.local_clock_time is None


def test_local_clock_time_kept_for_stated_time() -> None:
    ev = TimeEvidence.model_validate(
        {
            "kind": "STATED_TIME",
            "situation": "MORNING",
            "localClockTime": "09:00",
            "evidenceText": "x",
        }
    )
    assert ev.local_clock_time == "09:00"


def test_stated_time_without_clock_is_null_not_guessed() -> None:
    ev = TimeEvidence.model_validate(
        {"kind": "STATED_TIME", "situation": "OPENING", "evidenceText": "오픈하자마자 왔어요"}
    )
    assert ev.local_clock_time is None


# ---------- 평가 (spec §5.3) ----------


def test_rating_outside_enum_becomes_undetermined() -> None:
    r = Ratings.model_validate({"taste": "VERY_GOOD", "wait": "NEGATIVE", "price": None})
    assert (r.taste, r.wait, r.price) == ("UNDETERMINED", "NEGATIVE", "NONE")


def test_missing_rating_is_none_not_positive() -> None:
    assert Ratings().model_dump() == dict.fromkeys(Ratings.model_fields, "NONE")


# ---------- 후보 근거 연결 (spec §5.3) ----------


def test_candidate_without_clue_refs_is_dropped() -> None:
    result = _interpretation(_candidate(), _candidate(candidate_id="c2", clue_refs=[]))
    assert [c.candidate_id for c in result.candidates] == ["c1"]


def test_candidate_with_out_of_range_clue_ref_is_dropped() -> None:
    observation = ObservationResult.model_validate(
        {"video_id": "abc", "clues": [{"start_sec": 0, "end_sec": 5, "clue_type": "SPEECH"}]}
    )
    result = _interpretation(
        _candidate(candidate_id="ok", clue_refs=[0]),
        _candidate(candidate_id="too_big", clue_refs=[0, 1]),
        _candidate(candidate_id="negative", clue_refs=[-1]),
    )
    kept = link_to_observation(result, observation)
    assert [c.candidate_id for c in kept.candidates] == ["ok"]


def test_link_to_observation_rejects_other_video() -> None:
    observation = ObservationResult.model_validate({"video_id": "other", "clues": []})
    with pytest.raises(ValueError, match="different videos"):
        link_to_observation(_interpretation(_candidate()), observation)


def test_search_queries_capped_at_three() -> None:
    result = _interpretation(_candidate(search_queries=["a", "b", "c", "d"]))
    assert result.candidates[0].search_queries == ["a", "b", "c"]


def test_blank_branch_hint_becomes_none() -> None:
    result = _interpretation(_candidate(branch_hint="  "))
    assert result.candidates[0].branch_hint is None


# ---------- API (spec §3) ----------


def test_request_ignores_nothing_user_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateJobRequest.model_validate(
            {
                "requestId": "7a1d2e3f-4b5c-4d6e-8f70-819a2b3c4d5e",
                "destination": "오사카",
                "userId": "attacker",
            }
        )


def test_request_destination_is_trimmed() -> None:
    req = CreateJobRequest.model_validate(
        {"requestId": "7a1d2e3f-4b5c-4d6e-8f70-819a2b3c4d5e", "destination": "  오사카 "}
    )
    assert req.destination == "오사카"
    assert req.styles == []
    assert req.companion is None


def test_patch_preferences_tracks_sent_fields() -> None:
    req = UpdatePreferencesRequest.model_validate({"companion": None})
    assert req.model_fields_set == {"companion"}


def test_error_response_shape() -> None:
    body = ErrorResponse.model_validate(
        {
            "error": {"code": "DUPLICATE_REQUEST", "message": "이미 접수된 요청"},
            "jobId": "3f2b8c1e-6d4a-4b7e-9c2f-1a2b3c4d5e6f",
        }
    ).model_dump(mode="json", exclude_none=True)
    assert body == {
        "error": {"code": "DUPLICATE_REQUEST", "message": "이미 접수된 요청"},
        "jobId": "3f2b8c1e-6d4a-4b7e-9c2f-1a2b3c4d5e6f",
    }


# ---------- DynamoDB 아이템 (spec §4) ----------


def _evidence(**overrides: Any) -> dict[str, Any]:
    return {
        "placeId": "p1",
        "sk": PlaceEvidenceItem.make_sk("ch1", "abc", "v1-haiku45", 750),
        "videoId": "abc",
        "channelId": "ch1",
        "analysisVersion": "v1-haiku45",
        "evidenceKey": PlaceEvidenceItem.make_evidence_key("p1", "v1-haiku45", 750),
        "visitStatus": "VISITED",
        "matchStatus": "CONFIRMED",
        "videoTimeRange": {"startSec": 750, "endSec": 905},
        "evidenceText": "맛있어요",
        **overrides,
    }


def test_evidence_keys_follow_spec_format() -> None:
    item = PlaceEvidenceItem.model_validate(_evidence())
    assert item.sk == "EVID#ch1#abc#v1-haiku45#750"
    assert item.evidence_key == "p1#v1-haiku45#750"


def test_evidence_text_truncated_to_200() -> None:
    item = PlaceEvidenceItem.model_validate(_evidence(evidenceText="가" * 250))
    assert len(item.evidence_text) == 200


def test_result_evidence_text_truncated_to_200() -> None:
    link = EvidenceLink.model_validate(
        {"channelId": "ch1", "videoId": "abc", "startSec": 0, "text": "나" * 201}
    )
    assert len(link.text) == 200


def test_items_dump_as_camel_case() -> None:
    dumped = PlaceEvidenceItem.model_validate(_evidence()).model_dump(mode="json")
    assert "videoTimeRange" in dumped
    assert dumped["videoTimeRange"] == {"startSec": 750, "endSec": 905}


def test_dynamodb_decimals_are_accepted() -> None:
    # boto3 resource는 숫자를 Decimal로 돌려준다
    item = CoordCacheItem.model_validate(
        {
            "placeId": "p1",
            "lat": Decimal("34.6687"),
            "lng": Decimal("135.5013"),
            "expiresAt": Decimal("1790000000"),
        }
    )
    assert item.expires_at == 1790000000
    assert item.lat == pytest.approx(34.6687)


def test_job_item_never_holds_raw_guest_token() -> None:
    with pytest.raises(ValidationError):
        JobItem.model_validate(
            {
                "jobId": "3f2b8c1e-6d4a-4b7e-9c2f-1a2b3c4d5e6f",
                "requestId": "7a1d2e3f-4b5c-4d6e-8f70-819a2b3c4d5e",
                "guestAccessToken": "a" * 43,
                "status": "QUEUED",
                "request": {"destination": "오사카"},
                "createdAt": "2026-10-14T12:00:00Z",
                "updatedAt": "2026-10-14T12:00:00Z",
            }
        )


# ---------- 결정 0002 ----------


def test_scene_evidence_outside_day_night_is_dropped_from_ai_output() -> None:
    result = _interpretation(
        _candidate(
            time_evidence=[
                {"kind": "SCENE", "situation": "LUNCH_PEAK", "evidence_text": "가게 안 장면"},
                {"kind": "SCENE", "situation": "NIGHT", "evidence_text": "야경 장면"},
                {
                    "kind": "WAIT_EXPERIENCE",
                    "situation": "LUNCH_PEAK",
                    "evidence_text": "40분 대기",
                },
            ]
        )
    )
    kept = [(e.kind, e.situation) for e in result.candidates[0].time_evidence]
    assert kept == [("SCENE", "NIGHT"), ("WAIT_EXPERIENCE", "LUNCH_PEAK")]


@pytest.mark.parametrize("situation", ["DAY", "NIGHT"])
def test_scene_evidence_allows_day_and_night(situation: str) -> None:
    ev = TimeEvidence.model_validate(
        {"kind": "SCENE", "situation": situation, "evidenceText": "장면"}
    )
    assert ev.situation == situation


def test_scene_evidence_with_other_situation_rejected_when_stored() -> None:
    with pytest.raises(ValidationError, match="DAY or NIGHT"):
        TimeEvidence.model_validate(
            {"kind": "SCENE", "situation": "OPENING", "evidenceText": "장면"}
        )


def test_video_ref_starts_pending() -> None:
    ref = VideoRef.model_validate({"videoId": "abc", "channelId": "ch1", "analysisVersion": "v1"})
    assert ref.state == "PENDING"

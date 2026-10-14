"""규칙 테스트용 아이템 생성 도우미."""

from typing import Any

from shared.schemas.items import PlaceEvidenceItem, VideoRef

VERSION = "v1-haiku45"


def ref(video_id: str, channel_id: str, state: str = "DONE", **kw: Any) -> VideoRef:
    return VideoRef.model_validate(
        {
            "videoId": video_id,
            "channelId": channel_id,
            "analysisVersion": VERSION,
            "state": state,
            **kw,
        }
    )


def evidence(
    place_id: str,
    channel_id: str,
    video_id: str,
    start_sec: int = 0,
    *,
    visit: str = "VISITED",
    ratings: dict[str, str] | None = None,
    time: list[dict[str, Any]] | None = None,
    version: str = VERSION,
    match: str = "CONFIRMED",
) -> PlaceEvidenceItem:
    return PlaceEvidenceItem.model_validate(
        {
            "placeId": place_id,
            "sk": PlaceEvidenceItem.make_sk(channel_id, video_id, version, start_sec),
            "videoId": video_id,
            "channelId": channel_id,
            "analysisVersion": version,
            "evidenceKey": PlaceEvidenceItem.make_evidence_key(place_id, version, start_sec),
            "visitStatus": visit,
            "matchStatus": match,
            "videoTimeRange": {"startSec": start_sec, "endSec": start_sec + 10},
            "ratings": ratings or {},
            "evidenceText": "근거",
            "visitTimeEvidence": [{"evidenceText": "근거", **t} for t in (time or [])],
        }
    )

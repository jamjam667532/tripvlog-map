"""[M8] 관심사 제안기 (결정 0011). 실제 게이트웨이는 부르지 않는다."""

import json
from typing import Any

import pytest

from shared.clients.bedrock import GatewayChat
from shared.clients.errors import InvalidModelOutput
from shared.clients.interests import MAX_DESCRIPTION_CHARS, GatewayInterestExtractor
from shared.schemas.taste import ChannelInfo, ChannelVideo
from tests.unit.clients.transport import RecordingTransport


def _reply(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {}}


def _extractor(t: RecordingTransport) -> GatewayInterestExtractor:
    return GatewayInterestExtractor(
        GatewayChat("bedrock-haiku", api_key="k", base_url="https://gw", transport=t)
    )


CHANNELS = [ChannelInfo(channel_id="c1", title="건축 탐구", description="x" * 500)]
LIKED = [ChannelVideo(video_id="v1", channel_id="c9", title="안도 다다오 투어")]


def test_proposals_parsed_and_prompt_has_ids_and_short_descriptions() -> None:
    out = {
        "interests": [
            {"label": "건축", "evidence_ids": ["c1", "v1"], "search_terms": ["건축 투어"]}
        ]
    }
    t = RecordingTransport(lambda req: (200, _reply(json.dumps(out, ensure_ascii=False))))
    got = _extractor(t).extract(CHANNELS, LIKED)
    assert [(p.label, p.evidence_ids) for p in got] == [("건축", ["c1", "v1"])]
    user = json.loads(t.body()["messages"][1]["content"])
    assert user["channels"][0]["id"] == "c1"
    assert len(user["channels"][0]["description"]) == MAX_DESCRIPTION_CHARS
    assert user["liked"] == [{"id": "v1", "title": "안도 다다오 투어"}]


def test_invalid_output_retried_then_fails() -> None:
    t = RecordingTransport(lambda req: (200, _reply("nope")))
    with pytest.raises(InvalidModelOutput):
        _extractor(t).extract(CHANNELS, LIKED)
    assert len(t.requests) == 2

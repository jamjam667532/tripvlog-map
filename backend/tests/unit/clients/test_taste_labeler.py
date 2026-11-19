"""[M8] 채널 취향 라벨 제안기 (결정 0010). 실제 게이트웨이는 부르지 않는다."""

import json
from typing import Any

import pytest

from shared.clients.bedrock import GatewayChat
from shared.clients.errors import InvalidModelOutput
from shared.clients.http import HttpRequest
from shared.clients.taste import MAX_CHANNELS_PER_CALL, GatewayTasteLabeler
from shared.schemas.taste import ChannelInfo
from tests.unit.clients.transport import RecordingTransport


def _reply(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}], "usage": {}}


def _labeler(t: RecordingTransport) -> GatewayTasteLabeler:
    chat = GatewayChat("bedrock-haiku", api_key="k", base_url="https://gw", transport=t)
    return GatewayTasteLabeler(chat)


CHANNELS = [ChannelInfo(channel_id="c1", title="여행 채널", description="일본 소도시 여행")]


def test_labels_parsed_and_unknown_channels_dropped() -> None:
    labels = {
        "labels": [
            {
                "channel_id": "c1",
                "travel": "YES",
                "styles": ["관광·역사"],
                "evidence": "소도시 여행",
            },
            {"channel_id": "made-up", "travel": "YES", "styles": [], "evidence": None},
            {"channel_id": "c1", "travel": "NO", "styles": [], "evidence": None},
        ]
    }
    t = RecordingTransport(lambda req: (200, _reply("```json\n" + json.dumps(labels) + "\n```")))
    out = _labeler(t).label(CHANNELS)
    assert [(lb.channel_id, lb.travel) for lb in out] == [("c1", "YES")]
    sent = t.body()
    assert sent["model"] == "bedrock-haiku"
    user = json.loads(sent["messages"][1]["content"])
    assert user == [{"channel_id": "c1", "title": "여행 채널", "description": "일본 소도시 여행"}]


def test_invalid_output_retried_once_then_fails() -> None:
    t = RecordingTransport(lambda req: (200, _reply("not json")))
    with pytest.raises(InvalidModelOutput):
        _labeler(t).label(CHANNELS)
    assert len(t.requests) == 2


def test_channels_split_into_calls() -> None:
    def respond(req: HttpRequest) -> tuple[int, Any]:
        rows = json.loads(json.loads(req.body or b"{}")["messages"][1]["content"])
        return 200, _reply(
            json.dumps(
                {"labels": [{"channel_id": r["channel_id"], "travel": "UNKNOWN"} for r in rows]}
            )
        )

    t = RecordingTransport(respond)
    many = [ChannelInfo(channel_id=f"c{i}") for i in range(MAX_CHANNELS_PER_CALL + 5)]
    out = _labeler(t).label(many)
    assert len(t.requests) == 2
    assert len(out) == len(many)

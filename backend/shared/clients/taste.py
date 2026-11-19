"""[M8] 채널 취향 라벨 제안 (결정 0010). 학교 게이트웨이로 Bedrock 모델을 부른다.

입력은 공개 채널의 제목·설명뿐이다. 사용자 ID·이메일·토큰은 넘기지 않는다.
라벨은 제안일 뿐이다. 근거 확인(rules/taste.accept_label)과 사용자 확인을 거쳐야 저장된다.
"""

import json
from collections.abc import Sequence
from typing import Protocol

from pydantic import ValidationError

from shared.clients.ai_schema import ai_json_schema
from shared.clients.bedrock import MAX_ATTEMPTS, GatewayChat, message_text
from shared.clients.errors import InvalidModelOutput
from shared.clients.prompts import load_prompt
from shared.schemas.taste import ChannelInfo, ChannelTasteLabel, ChannelTasteLabels

LABEL_VERSION = "taste-v1"  # 프롬프트·스키마가 바뀌면 올린다. 채널 라벨 캐시가 다시 만들어진다
MAX_CHANNELS_PER_CALL = 30  # 게이트웨이 출력 4,096토큰 안에 들게
MAX_DESCRIPTION_CHARS = 300


class TasteLabeler(Protocol):
    def label(self, channels: Sequence[ChannelInfo]) -> list[ChannelTasteLabel]: ...


def channels_prompt(channels: Sequence[ChannelInfo]) -> str:
    rows = [
        {
            "channel_id": c.channel_id,
            "title": c.title,
            "description": c.description[:MAX_DESCRIPTION_CHARS],
        }
        for c in channels
    ]
    return json.dumps(rows, ensure_ascii=False)


class GatewayTasteLabeler:
    def __init__(self, chat: GatewayChat) -> None:
        self._chat = chat
        schema = json.dumps(ai_json_schema(ChannelTasteLabels), ensure_ascii=False)
        self._system = (
            load_prompt("taste")
            + "\n\n## 출력 JSON 스키마 (반드시 이 형식 그대로, JSON 하나만 출력)\n"
            + schema
        )

    def __repr__(self) -> str:
        return f"GatewayTasteLabeler({self._chat!r})"

    def label(self, channels: Sequence[ChannelInfo]) -> list[ChannelTasteLabel]:
        out: list[ChannelTasteLabel] = []
        for i in range(0, len(channels), MAX_CHANNELS_PER_CALL):
            out.extend(self._label_chunk(channels[i : i + MAX_CHANNELS_PER_CALL]))
        return out

    def _label_chunk(self, chunk: Sequence[ChannelInfo]) -> list[ChannelTasteLabel]:
        asked = {c.channel_id for c in chunk}
        for _ in range(MAX_ATTEMPTS):
            data = self._chat.complete(self._system, channels_prompt(chunk))
            try:
                parsed = ChannelTasteLabels.model_validate(json.loads(message_text(data)))
            except (KeyError, IndexError, json.JSONDecodeError, ValidationError, TypeError):
                continue
            seen: set[str] = set()
            kept: list[ChannelTasteLabel] = []
            for label in parsed.labels:
                # 입력에 없는 채널은 버린다. 같은 채널이 두 번 나오면 처음 것만
                if label.channel_id in asked and label.channel_id not in seen:
                    seen.add(label.channel_id)
                    kept.append(label)
            return kept
        raise InvalidModelOutput("llm-gateway", MAX_ATTEMPTS)

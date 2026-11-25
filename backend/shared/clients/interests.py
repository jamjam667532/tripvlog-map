"""[M8] 구독·좋아요에서 관심사 제안 (결정 0011). 학교 게이트웨이로 Bedrock 모델을 부른다.

입력은 공개 채널·영상의 제목과 설명 앞부분뿐이다. 사용자 ID·이메일·토큰은 넘기지 않는다.
제안은 rules/interests.validate_interests에서 근거를 검증한 뒤에만 쓴다.
"""

import json
from collections.abc import Sequence
from typing import Protocol

from pydantic import ValidationError

from shared.clients.ai_schema import ai_json_schema
from shared.clients.bedrock import MAX_ATTEMPTS, GatewayChat, message_text
from shared.clients.errors import InvalidModelOutput
from shared.clients.prompts import load_prompt
from shared.schemas.taste import ChannelInfo, ChannelVideo, InterestProposal, InterestProposals

INTERESTS_VERSION = "interests-v1"  # 프롬프트·스키마가 바뀌면 올린다
MAX_DESCRIPTION_CHARS = 120


class InterestExtractor(Protocol):
    def extract(
        self, channels: Sequence[ChannelInfo], liked: Sequence[ChannelVideo]
    ) -> list[InterestProposal]: ...


def interests_prompt(channels: Sequence[ChannelInfo], liked: Sequence[ChannelVideo]) -> str:
    body = {
        "channels": [
            {
                "id": c.channel_id,
                "title": c.title,
                "description": c.description[:MAX_DESCRIPTION_CHARS],
            }
            for c in channels
        ],
        "liked": [{"id": v.video_id, "title": v.title} for v in liked],
    }
    return json.dumps(body, ensure_ascii=False)


class GatewayInterestExtractor:
    def __init__(self, chat: GatewayChat) -> None:
        self._chat = chat
        schema = json.dumps(ai_json_schema(InterestProposals), ensure_ascii=False)
        self._system = (
            load_prompt("interests")
            + "\n\n## 출력 JSON 스키마 (반드시 이 형식 그대로, JSON 하나만 출력)\n"
            + schema
        )

    def __repr__(self) -> str:
        return f"GatewayInterestExtractor({self._chat!r})"

    def extract(
        self, channels: Sequence[ChannelInfo], liked: Sequence[ChannelVideo]
    ) -> list[InterestProposal]:
        user_text = interests_prompt(channels, liked)
        for _ in range(MAX_ATTEMPTS):
            data = self._chat.complete(self._system, user_text)
            try:
                return InterestProposals.model_validate(json.loads(message_text(data))).interests
            except (KeyError, IndexError, json.JSONDecodeError, ValidationError, TypeError):
                continue
        raise InvalidModelOutput("llm-gateway", MAX_ATTEMPTS)

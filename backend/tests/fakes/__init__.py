"""외부 API 가짜 구현. 테스트에서 실제 유료 API(Gemini, Places, Bedrock, YouTube)를 부르지 않는다.

각 가짜는 shared.clients의 Protocol을 만족하고, 호출 기록을 남겨 "몇 번 불렸는지"를 검사할 수 있다.
"""

from tests.fakes.clients import (
    FakeBedrock,
    FakeEmbedder,
    FakeGemini,
    FakeInterestExtractor,
    FakePlaces,
    FakeStarter,
    FakeTasteLabeler,
    FakeYouTube,
    FakeYouTubeUser,
)

__all__ = [
    "FakeBedrock",
    "FakeEmbedder",
    "FakeGemini",
    "FakeInterestExtractor",
    "FakePlaces",
    "FakeStarter",
    "FakeTasteLabeler",
    "FakeYouTube",
    "FakeYouTubeUser",
]

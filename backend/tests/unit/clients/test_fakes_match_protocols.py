"""가짜 구현이 실제 클라이언트와 같은 인터페이스를 갖는지 mypy가 검사하게 한다."""

from shared.clients.bedrock import BedrockInterpreter
from shared.clients.gemini import GeminiObserver
from shared.clients.orchestrator import JobStarter, StepFunctionsStarter
from shared.clients.places import PlacesClient
from shared.clients.youtube import YouTubeClient
from tests.fakes import FakeBedrock, FakeGemini, FakePlaces, FakeStarter, FakeYouTube


def test_fakes_satisfy_client_protocols() -> None:
    yt: YouTubeClient = FakeYouTube({}, [])
    gm: GeminiObserver = FakeGemini({})
    br: BedrockInterpreter = FakeBedrock({})
    pl: PlacesClient = FakePlaces({})
    st: JobStarter = FakeStarter()
    assert all((yt, gm, br, pl, st))


def test_real_starter_satisfies_protocol() -> None:
    st: JobStarter = StepFunctionsStarter("arn", client=object())
    assert st

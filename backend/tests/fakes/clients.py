import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from shared.clients.bedrock import Interpretation
from shared.clients.errors import ExternalApiError, InvalidModelOutput
from shared.clients.gemini import Observation
from shared.clients.places import MAX_CALLS_PER_CANDIDATE
from shared.clients.youtube import SEARCH_UNITS, VIDEOS_UNITS, SearchOrder
from shared.schemas.interpretation import InterpretationResult, link_to_observation
from shared.schemas.observation import ObservationResult
from shared.schemas.places import GeoPoint, PlaceHit
from shared.schemas.youtube import VideoMeta


class FakeYouTube:
    def __init__(self, search: Mapping[str, Sequence[str]], metas: Sequence[VideoMeta]) -> None:
        self._search = search
        self._metas = {m.video_id: m for m in metas}
        self.search_calls: list[tuple[str, SearchOrder]] = []
        self.units_used = 0

    def search(
        self, query: str, *, order: SearchOrder, published_after: datetime, max_results: int = 25
    ) -> list[str]:
        self.search_calls.append((query, order))
        self.units_used += SEARCH_UNITS
        return list(self._search.get(query, []))[:max_results]

    def videos(self, video_ids: Sequence[str]) -> list[VideoMeta]:
        self.units_used += VIDEOS_UNITS
        return [self._metas[v] for v in dict.fromkeys(video_ids) if v in self._metas]


class FakeGemini:
    """영상별 관찰 결과를 돌려준다. 값이 없으면 실제처럼 InvalidModelOutput."""

    TOKENS_PER_CALL = 1000

    def __init__(self, observations: Mapping[str, ObservationResult]) -> None:
        self._observations = observations
        self.calls: Counter[str] = Counter()
        self._lock = threading.Lock()

    def observe(self, video_id: str) -> Observation:
        with self._lock:
            self.calls[video_id] += 1
        obs = self._observations.get(video_id)
        if obs is None:
            raise InvalidModelOutput("gemini", 2)
        return Observation(obs, self.TOKENS_PER_CALL)


class FakeBedrock:
    def __init__(self, interpretations: Mapping[str, InterpretationResult]) -> None:
        self._interpretations = interpretations
        self.calls: Counter[str] = Counter()

    def interpret(self, observation: ObservationResult, analysis_version: str) -> Interpretation:
        self.calls[observation.video_id] += 1
        found = self._interpretations.get(observation.video_id)
        if found is None:
            raise InvalidModelOutput("bedrock", 2)
        result = found.model_copy(update={"analysis_version": analysis_version})
        return Interpretation(link_to_observation(result, observation), 100, 50)


class FakePlaces:
    """검색어별 결과. 실제 클라이언트와 같은 호출 예산(후보당 2회)을 지킨다."""

    def __init__(
        self, hits: Mapping[str, Sequence[PlaceHit]], cities: Mapping[str, GeoPoint] | None = None
    ) -> None:
        self._hits = hits
        self._cities = cities or {}
        self.queries: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.queries)

    def locate(self, text: str) -> GeoPoint | None:
        self.queries.append(text)
        return self._cities.get(text)

    def search_candidate(self, queries: Sequence[str], *, bias: GeoPoint | None) -> list[PlaceHit]:
        hits: list[PlaceHit] = []
        for q in list(queries)[:MAX_CALLS_PER_CANDIDATE]:
            self.queries.append(q)
            hits = list(self._hits.get(q, []))
            if hits:
                break
        return hits


class FakeStarter:
    """Step Functions 대신 시작 요청만 기록한다."""

    ARN_PREFIX = "arn:aws:states:us-east-1:000000000000:execution:analyze:"

    def __init__(self, *, fail: bool = False) -> None:
        self.started: list[str] = []
        self._fail = fail

    def start(self, job_id: str) -> str:
        if self._fail:
            raise ExternalApiError("stepfunctions", 500, "fake failure")
        self.started.append(job_id)
        return self.ARN_PREFIX + job_id

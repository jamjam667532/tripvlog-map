import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from shared.clients.bedrock import Interpretation
from shared.clients.errors import ExternalApiError, InvalidModelOutput
from shared.clients.gemini import Observation
from shared.clients.places import MAX_CALLS_PER_CANDIDATE
from shared.clients.youtube import LIST_UNITS, SEARCH_UNITS, VIDEOS_UNITS, SearchOrder
from shared.schemas.interpretation import InterpretationResult, link_to_observation
from shared.schemas.observation import ObservationResult
from shared.schemas.places import GeoPoint, PlaceHit
from shared.schemas.taste import ChannelInfo, ChannelTasteLabel, ChannelVideo, InterestProposal
from shared.schemas.youtube import VideoMeta


class FakeYouTube:
    def __init__(
        self,
        search: Mapping[str, Sequence[str]],
        metas: Sequence[VideoMeta],
        *,
        channels: Sequence[ChannelInfo] = (),
        uploads: Mapping[str, Sequence[ChannelVideo]] | None = None,
    ) -> None:
        self._search = search
        self._metas = {m.video_id: m for m in metas}
        self._channels = {c.channel_id: c for c in channels}
        self._uploads = uploads or {}
        self.search_calls: list[tuple[str, SearchOrder]] = []
        self.upload_calls: list[str] = []
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

    def channels(self, channel_ids: Sequence[str]) -> list[ChannelInfo]:
        self.units_used += LIST_UNITS
        return [self._channels[c] for c in dict.fromkeys(channel_ids) if c in self._channels]

    def uploads(self, channel_id: str, max_results: int = 50) -> list[ChannelVideo]:
        self.upload_calls.append(channel_id)
        self.units_used += LIST_UNITS
        return list(self._uploads.get(channel_id, []))[:max_results]


class FakeYouTubeUser:
    """사용자 토큰으로 읽는 구독·좋아요. reject=True면 Google이 토큰을 거부한 것처럼 401."""

    def __init__(
        self,
        subscriptions: Sequence[str] = (),
        liked: Sequence[ChannelVideo] = (),
        *,
        reject: bool = False,
    ) -> None:
        self._subscriptions = list(subscriptions)
        self._liked = list(liked)
        self._reject = reject
        self.tokens: list[str] = []

    def for_token(self, token: str) -> "FakeYouTubeUser":
        self.tokens.append(token)
        return self

    def subscription_channel_ids(self) -> list[str]:
        if self._reject:
            raise ExternalApiError("youtube", 401)
        return list(self._subscriptions)

    def liked_videos(self) -> list[ChannelVideo]:
        if self._reject:
            raise ExternalApiError("youtube", 401)
        return list(self._liked)


class FakeTasteLabeler:
    """채널별 라벨을 돌려준다. fail=True면 게이트웨이 오류처럼 예외."""

    def __init__(self, labels: Mapping[str, ChannelTasteLabel], *, fail: bool = False) -> None:
        self._labels = labels
        self._fail = fail
        self.asked: list[list[str]] = []

    def label(self, channels: Sequence[ChannelInfo]) -> list[ChannelTasteLabel]:
        self.asked.append([c.channel_id for c in channels])
        if self._fail:
            raise ExternalApiError("llm-gateway", 500)
        return [self._labels[c.channel_id] for c in channels if c.channel_id in self._labels]


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


class FakeEmbedder:
    """키워드마다 한 축을 쓰는 결정적 임베딩. 같은 관심사 단어가 있으면 코사인이 높다."""

    KEYWORDS = ("건축", "역사", "애니", "맛집", "카페")

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self._fail:
            raise ExternalApiError("llm-gateway", 500)
        return [[1.0 if k in t else 0.0 for k in self.KEYWORDS] + [0.05] for t in texts]


class FakeInterestExtractor:
    def __init__(self, proposals: Sequence[InterestProposal], *, fail: bool = False) -> None:
        self._proposals = list(proposals)
        self._fail = fail
        self.calls = 0

    def extract(
        self, channels: Sequence[ChannelInfo], liked: Sequence[ChannelVideo]
    ) -> list[InterestProposal]:
        self.calls += 1
        if self._fail:
            raise ExternalApiError("llm-gateway", 500)
        return list(self._proposals)

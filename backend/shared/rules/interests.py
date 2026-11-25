"""[M8] 관심사 기반 테마 추천 규칙 (결정 0011). 순수 함수.

- 근거 검증: Bedrock이 제안한 관심사는 근거 ID가 입력에 있을 때만 쓰고, 비중은 근거 수로 정한다.
- 관심사 벡터: 관심사 문장 + 근거 채널·영상 글의 임베딩 평균(2026-11-25 시험에서 짧은 문장만 쓰면
  "에도 시대 유물"→역사를 놓쳤다).
- 유사도: 코사인 유사도 x 비중 보정 + 검색어 단어가 영상 글에 있으면 가산("현대건축"을 놓치지 않게).
- 구성: 개인화 3(구독 채널 영상 → 관심사 유사도 순) + 일반 2. 처음 가는 도시의 대표 장소를 지킨다.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from shared.rules.selection import Selection
from shared.schemas.items import UserInterest, UserItem
from shared.schemas.taste import InterestProposal
from shared.schemas.youtube import VideoMeta

MAX_INTERESTS = 5
MAX_TERMS = 3
MAX_TERM_CHARS = 20
MAX_LABEL_CHARS = 20
THEME_SEARCHES = 2  # 검색할 때 테마 검색을 하는 상위 관심사 수(검색 1회 100 unit, 캐시 있음)
MAX_PERSONALIZED = 3  # 요청 5개 중 개인화 자리(결정 0011: 관심사 3 + 일반 2)
# TODO(tune): titan-embed-v2 실측(2026-11-25) 관련 0.34, 덜 관련 0.21, 무관 0.04
MIN_THEME_SCORE = 0.25
SUBSCRIBED_THEME = "구독 채널"
LEXICAL_BONUS = 0.15  # 관심사 검색어 단어가 영상 제목·설명에 있으면 더한다
MAX_EVIDENCE_TEXTS = 10  # 관심사 벡터에 섞는 근거 글 수(임베딩 비용 상한)
# 검색어에 흔히 붙는 말은 단어 일치에서 뺀다
GENERIC_WORDS = frozenset({"여행", "투어", "명소", "답사", "산책", "쇼핑", "브이로그", "코스"})


@dataclass(frozen=True)
class ValidInterest:
    label: str
    weight: float
    search_terms: list[str]
    evidence_ids: list[str]


def validate_interests(
    proposals: Sequence[InterestProposal],
    known_ids: set[str],
    *,
    max_interests: int = MAX_INTERESTS,
) -> list[ValidInterest]:
    """입력에 없는 근거 ID는 버리고, 근거가 없는 관심사도 버린다. 비중 = 근거 수 / 전체 근거 수."""
    kept: list[tuple[str, list[str], list[str]]] = []
    seen: set[str] = set()
    for p in proposals:
        label = " ".join(p.label.split())[:MAX_LABEL_CHARS]
        evidence = list(dict.fromkeys(i for i in p.evidence_ids if i in known_ids))
        if not label or not evidence or label in seen:
            continue
        seen.add(label)
        terms = [" ".join(t.split())[:MAX_TERM_CHARS] for t in p.search_terms]
        terms = list(dict.fromkeys(t for t in terms if t))[:MAX_TERMS] or [f"{label} 여행"]
        kept.append((label, terms, evidence))
    total = sum(len(e) for _, _, e in kept)
    out = [ValidInterest(lb, round(len(e) / total, 2), t, e) for lb, t, e in kept]
    out.sort(key=lambda x: (-x.weight, x.label))
    return out[:max_interests]


def interest_text(label: str, terms: Sequence[str]) -> str:
    """관심사 임베딩에 쓰는 문장."""
    return f"{label} 여행: " + ", ".join(terms)


def video_text(meta: VideoMeta) -> str:
    """영상 임베딩에 쓰는 문장(제목 + 설명 앞부분)."""
    return f"{meta.title}\n{meta.description[:300]}"


def mean_vector(vectors: Sequence[Sequence[float]]) -> list[float]:
    """여러 벡터의 평균. 관심사 문장과 근거 글들을 하나의 관심사 벡터로 합친다."""
    n = len(vectors)
    return [sum(col) / n for col in zip(*vectors, strict=True)]


def term_words(terms: Sequence[str]) -> set[str]:
    """검색어의 의미 있는 단어(2글자 이상, 흔한 말 제외)."""
    words = {w for t in terms for w in t.split() if len(w) >= 2}
    return words - GENERIC_WORDS


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


def active_interests(user: UserItem | None) -> list[UserInterest]:
    """사용자가 끄지 않은 관심사. 유튜브 연결이 없으면 빈 목록."""
    if user is None or user.youtube is None:
        return []
    hidden = set(user.preferences.hidden_interests)
    return [i for i in user.youtube.interests if i.label not in hidden]


def theme_queries(
    interests: Sequence[UserInterest], destination: str, *, limit: int = THEME_SEARCHES
) -> list[str]:
    """상위 관심사의 첫 검색어로 테마 검색어를 만든다. 예: "도쿄 건축 투어"."""
    return [f"{destination.strip()} {i.search_terms[0]}" for i in interests[:limit]]


def theme_score(
    video_vector: Sequence[float], interests: Sequence[UserInterest], text: str = ""
) -> tuple[str | None, float]:
    """(가장 가까운 관심사, 점수).

    점수 = 코사인 유사도 x (0.8 + 0.2 x 관심사 비중) + 검색어 단어가 글에 있으면 LEXICAL_BONUS.
    """
    best: tuple[str | None, float] = (None, 0.0)
    for i in interests:
        s = cosine(video_vector, i.embedding) * (0.8 + 0.2 * i.weight)
        if text and any(w in text for w in term_words(i.search_terms)):
            s += LEXICAL_BONUS
        if s > best[1]:
            best = (i.label, round(s, 4))
    return best


@dataclass(frozen=True)
class Themed:
    meta: VideoMeta
    theme: str
    score: float


def compose(
    general: Selection,
    personal: Sequence[VideoMeta],
    themed: Sequence[Themed],
    *,
    max_videos: int,
    max_spares: int,
    max_personalized: int = MAX_PERSONALIZED,
    max_personal: int = 2,
    min_score: float = MIN_THEME_SCORE,
) -> tuple[Selection, dict[str, tuple[str, float | None]]]:
    """개인화 자리(구독 채널 영상 → 관심사 유사도 순, 기준 이상만)를 채우고 나머지는 일반 선택으로.

    채널당 1개. 돌려주는 dict는 영상 ID → (관심사 이름, 점수). 일반 자리 영상은 없다.
    """
    chosen: list[VideoMeta] = []
    themes: dict[str, tuple[str, float | None]] = {}
    channels: set[str] = set()

    def take(meta: VideoMeta, theme: str, score: float | None) -> None:
        chosen.append(meta)
        channels.add(meta.channel_id)
        themes[meta.video_id] = (theme, score)

    for meta in personal:
        if len(chosen) >= min(max_personal, max_personalized):
            break
        if meta.channel_id not in channels:
            take(meta, SUBSCRIBED_THEME, None)
    for t in sorted(themed, key=lambda x: -x.score):
        if len(chosen) >= max_personalized:
            break
        if t.score >= min_score and t.meta.channel_id not in channels:
            take(t.meta, t.theme, t.score)

    ids = {m.video_id for m in chosen}
    rest = [
        m
        for m in [*general.chosen, *general.spares]
        if m.channel_id not in channels and m.video_id not in ids
    ]
    room = max(0, max_videos - len(chosen))
    return Selection(chosen=chosen + rest[:room], spares=rest[room : room + max_spares]), themes


def place_theme_boosts(
    place_videos: Mapping[str, set[str]],
    video_themes: Mapping[str, tuple[str | None, float | None]],
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """장소는 자기가 나온 영상의 관심사 점수 중 가장 높은 값을 물려받는다. 관심사 이름도 함께."""
    boosts: dict[str, float] = {}
    names: dict[str, list[str]] = {}
    for place, videos in place_videos.items():
        pairs = [video_themes[v] for v in videos if v in video_themes]
        scores = [s for _, s in pairs if s is not None]
        labels = sorted({t for t, _ in pairs if t})
        if scores:
            boosts[place] = max(scores)
        if labels:
            names[place] = labels
    return boosts, names

"""[4] 방문 시간대 근거 요약 (spec §5.5, 기획서 "방문 시간대 근거 규칙").

- 종류(kind)·상황(situation)별로 서로 다른 채널 수를 센다. 채널당 한 번.
- 상충하는 근거는 합치지 않고 그대로 나열한다.
- "추천"은 CREATOR_TIP이 있거나, 같은 상황에서 대기가 짧았다(wait 긍정)는 채널이 2곳 이상일 때만.
- 장면 관찰(SCENE)·방문 시각 언급(STATED_TIME)만으로는 추천하지 않는다.
"""

from collections import defaultdict
from collections.abc import Iterable

from shared.schemas.common import Situation, TimeEvidenceKind
from shared.schemas.items import PlaceEvidenceItem
from shared.schemas.result import TimeEvidenceSummary

MIN_CHANNELS_FOR_WAIT_RECOMMEND = 2

# 방문 경험이 있어야 성립하는 근거. 단순 언급(MENTIONED)에서는 쓰지 않는다(결정 0003-2)
_NEEDS_VISIT: frozenset[TimeEvidenceKind] = frozenset({"SCENE", "STATED_TIME", "WAIT_EXPERIENCE"})

_KIND_ORDER: dict[TimeEvidenceKind, int] = {
    "CREATOR_TIP": 0,
    "WAIT_EXPERIENCE": 1,
    "STATED_TIME": 2,
    "SCENE": 3,
}


def summarize_time_evidence(evidences: Iterable[PlaceEvidenceItem]) -> list[TimeEvidenceSummary]:
    channels: dict[tuple[TimeEvidenceKind, Situation], set[str]] = defaultdict(set)
    short_wait: dict[Situation, set[str]] = defaultdict(set)

    for item in evidences:
        for ev in item.visit_time_evidence:
            if ev.kind in _NEEDS_VISIT and item.visit_status != "VISITED":
                continue
            channels[(ev.kind, ev.situation)].add(item.channel_id)
            # 대기 방향은 같은 근거의 wait 평가로 판단한다(결정 0003-3)
            if ev.kind == "WAIT_EXPERIENCE" and item.ratings.wait == "POSITIVE":
                short_wait[ev.situation].add(item.channel_id)

    summaries = [
        TimeEvidenceSummary(
            kind=kind,
            situation=situation,
            channels=len(chs),
            recommend=_recommend(kind, situation, short_wait),
        )
        for (kind, situation), chs in channels.items()
    ]
    return sorted(summaries, key=lambda s: (_KIND_ORDER[s.kind], -s.channels, s.situation))


def _recommend(
    kind: TimeEvidenceKind, situation: Situation, short_wait: dict[Situation, set[str]]
) -> bool:
    if kind == "CREATOR_TIP":
        return True
    if kind == "WAIT_EXPERIENCE":
        return len(short_wait.get(situation, ())) >= MIN_CHANNELS_FOR_WAIT_RECOMMEND
    return False

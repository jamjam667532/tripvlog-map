"""지역 묶음 (spec §5.5). 좌표 격자로 가까운 장소를 묶는다. 일자·순서 개념은 없다.

이름은 Google 응답을 저장할 수 없어 "지역 1", "지역 2"…로 붙인다.
가장 높은 순위 장소가 있는 묶음이 "지역 1"이다(결정 0004-7).
"""

import math
from collections.abc import Sequence

# TODO(tune): 도시 크기에 맞게 조정. 약 2 km
CELL_KM = 2.0
KM_PER_DEG_LAT = 111.0


def _cell(lat: float, lng: float, cell_km: float) -> tuple[int, int]:
    lat_step = cell_km / KM_PER_DEG_LAT
    lng_step = cell_km / (KM_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
    return math.floor(lat / lat_step), math.floor(lng / lng_step)


def area_groups(
    ranked_points: Sequence[tuple[str, float, float]], *, cell_km: float = CELL_KM
) -> dict[str, str]:
    """(placeId, lat, lng)를 순위 순으로 받아 placeId → 지역 이름."""
    labels: dict[tuple[int, int], str] = {}
    result: dict[str, str] = {}
    for place_id, lat, lng in ranked_points:
        cell = _cell(lat, lng, cell_km)
        if cell not in labels:
            labels[cell] = f"지역 {len(labels) + 1}"
        result[place_id] = labels[cell]
    return result

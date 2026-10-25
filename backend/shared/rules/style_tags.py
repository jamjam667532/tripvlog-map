"""[1] 제목·설명란 키워드로 영상 스타일 태그를 붙인다 (spec §5.1 5단계).

스타일 태깅은 이 키워드 규칙만 쓴다(Nova Micro는 학교 게이트웨이에 없어 삭제, 결정 0007-1).
스타일 하나면 그 스타일, 둘 이상이면 "복합", 없으면 "분류불가".
"""

from collections.abc import Mapping
from typing import Literal

from shared.schemas.common import Style

StyleTag = Style | Literal["복합", "분류불가"]

# TODO(tune): experiments/의 dev 라벨로 조정한다
STYLE_KEYWORDS: Mapping[Style, tuple[str, ...]] = {
    "맛집": ("맛집", "먹방", "먹부림", "식당", "미식", "라멘", "스시", "이자카야", "오마카세"),
    "카페·포토스팟": ("카페", "디저트", "베이커리", "포토", "사진 명소", "감성"),
    "관광·역사": ("관광", "명소", "역사", "신사", "사원", "사찰", "박물관", "유적"),
    "쇼핑": ("쇼핑", "기념품", "하울", "돈키호테", "아울렛", "면세"),
    "가성비": ("가성비", "저렴", "저예산", "알뜰", "경비 정리"),
}


def video_styles(title: str, description: str = "") -> set[Style]:
    text = f"{title}\n{description}".casefold()
    return {style for style, words in STYLE_KEYWORDS.items() if any(w in text for w in words)}


def style_tag(title: str, description: str = "") -> StyleTag:
    styles = video_styles(title, description)
    if not styles:
        return "분류불가"
    if len(styles) > 1:
        return "복합"
    return next(iter(styles))

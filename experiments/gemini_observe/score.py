"""영상 ec6YBcndc4w 전용 채점: 기준선(10/15 실행, 단서 24개) 대비 핵심 단서 재현율.

키워드 포함 + 재생 위치 ±15초.
다른 영상은 정답 라벨(experiments/labels, M7-0)이 생기면 거기로 옮긴다.

  uv run python experiments/gemini_observe/score.py <tag> [--mmss]
  --mmss: 분:초를 붙여 쓴 값(1551 = 15:51)을 초로 바꿔 채점 (기존 정수 스키마 결과용)
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

OUT = Path(__file__).parent / "out"
TOL = 15

CORE = [
    ("P01 다카시마야", "place", 62, ["다카시마야", "타카시마야", "たかしまや", "高島屋"]),
    ("P02 かみなりずし", "place", 89, ["かみなり", "kaminari", "카미나리"]),
    ("P03 도톤보리 주소", "place", 171, ["542-0071", "dotonbori"]),
    ("P04 レンタル着物 岡本", "place", 353, ["岡本", "okamoto", "오카모토"]),
    ("P05 Katsugyu", "place", 391, ["katsugyu", "勝牛", "카츠규"]),
    ("P06 清水寺", "place", 491, ["清水寺", "기요미즈", "kiyomizu-dera", "kiyomizudera"]),
    ("P07 忠僕茶屋", "place", 515, ["忠僕"]),
    ("P08 北浜駅", "place", 663, ["北浜", "kitahama", "기타하마"]),
    ("P09 Embankment Coffee", "place", 713, ["embankment"]),
    ("P10 一蘭 心斎橋", "place", 788, ["一蘭", "ichiran", "이치란"]),
    ("P11 寿喜", "place", 953, ["寿喜", "kotobuki", "코토부키"]),
    ("U01 모르면 못찾을", "utter", 97, ["못찾을", "못 찾을", "못올", "못 올"]),
    ("U02 식감 차원", "utter", 139, ["식감이"]),
    ("U03 참치 기름기", "utter", 150, ["기름기"]),
    ("U04 스시 원탑", "utter", 166, ["원탑"]),
    ("U05 우설 카츠", "utter", 403, ["우설"]),
    ("U06 너무 맛있잖아", "utter", 420, ["맛있잖아"]),
    ("U07 먹어보세요 제발", "utter", 450, ["먹어보세요"]),
    ("U08 뷰가 너무", "utter", 730, ["뷰가"]),
    ("U09 10분만에 입장(대기)", "utter", 793, ["10분"]),
    ("U10 최애 라면", "utter", 854, ["최애"]),
    ("U11 후회없는", "utter", 866, ["후회"]),
    ("U12 고기가 녹아", "utter", 995, ["녹아"]),
    ("U13 궁합 환상", "utter", 1034, ["궁합"]),
]
POSTAL = ["542-0071", "605-0862", "605-0846", "541-0041", "542-0085", "542-0083"]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s).casefold())


def clue_text(c: dict) -> str:
    return " ".join(str(c.get(k) or "") for k in ("heard_name", "seen_text", "utterance", "scene"))


def main(tag: str, mmss: bool) -> None:
    clues = json.loads((OUT / f"obs_{tag}.json").read_text())["clues"]
    if mmss:
        for c in clues:
            for k in ("start_sec", "end_sec"):
                c[k] = (c[k] // 100) * 60 + c[k] % 100
    used, missed, got = set(), [], {"place": 0, "utter": 0}
    for cid, kind, t, keys in CORE:
        found = next(
            (
                i
                for i, c in enumerate(clues)
                if c["start_sec"] - TOL <= t <= c["end_sec"] + TOL
                and any(norm(k) in norm(clue_text(c)) for k in keys)
            ),
            None,
        )
        if found is None:
            missed.append(cid)
        else:
            used.add(found)
            got[kind] += 1
    text = norm(" ".join(clue_text(c) for c in clues))
    types: dict[str, int] = {}
    for c in clues:
        types[c["clue_type"]] = types.get(c["clue_type"], 0) + 1
    print(
        f"== {tag}{' (mmss→초)' if mmss else ''}: 단서 {len(clues)} {types}"
        f" | 장소 {got['place']}/11"
        f" | 평가원문 {got['utter']}/13 | 우편번호 {sum(p in text for p in POSTAL)}/6"
    )
    print("   놓침:", ", ".join(missed) or "-")
    for i, c in enumerate(clues):
        if i not in used:
            text = clue_text(c).strip()[:90]
            print(f"   기준선에 없음: [{c['start_sec']}] {c['clue_type']} {text}")


if __name__ == "__main__":
    main(sys.argv[1], "--mmss" in sys.argv)

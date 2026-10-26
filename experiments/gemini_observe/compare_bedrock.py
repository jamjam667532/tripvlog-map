"""[2-3] 실험: 같은 관찰 결과를 Bedrock과 규칙 기준선으로 처리해 비교한다.

정답 영상 ec6YBcndc4w 전용. 학교 LLM 게이트웨이를 실제로 부른다(단서 80개당 1회).
키는 출력하지 않는다.

  cd backend && PYTHONPATH=. uv run python ../experiments/gemini_observe/compare_bedrock.py G2

결과를 읽을 때 주의:
- 정답 장소 11곳·평가 문장 13개는 score.py의 CORE다. "평가 문장이 속한 장소"는 사람이 확인한
  값이 아니라 "그 발화 직전에 나온 정답 장소"로 둔 임시 정답이다.
- 규칙 기준선은 아래 두 가지로 간단하다. 더 똑똑한 규칙이면 결과가 달라질 수 있다.
- "평가 붙음"은 평가 항목이 NONE이 아니라는 뜻이다. 긍정/부정이 맞는지는 보지 않는다.
"""

import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

from score import CORE  # noqa: E402

from shared.clients.bedrock import ChunkedInterpreter, GatewayChatInterpreter  # noqa: E402
from shared.schemas.observation import ObservationResult  # noqa: E402

ADDR = re.compile(r"〒|\d{3}-\d{4}|Chuo Ward|Chome|丁目|Osaka,|大阪府")


def norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s).casefold())


def hits(s: str, keys: list[str]) -> bool:
    return any(norm(k) in norm(s) for k in keys)


def main() -> None:
    tag = sys.argv[1] if len(sys.argv) > 1 else "G2"
    env = dict(
        line.split("=", 1)
        for line in (ROOT / "experiments/.env").read_text().splitlines()
        if "=" in line
    )
    out = Path(__file__).parent / "out"
    obs = ObservationResult.model_validate_json((out / f"obs_{tag}.json").read_text())
    clues = obs.clues
    places = [(t, keys) for _, kind, t, keys in CORE if kind == "place"]
    utters = [(t, keys) for _, kind, t, keys in CORE if kind == "utter"]

    def text(c) -> str:
        return " ".join(str(getattr(c, k) or "") for k in ("heard_name", "seen_text", "utterance"))

    def truth(t: int) -> list[str] | None:
        before = [p for p in places if p[0] <= t]
        return max(before)[1] if before else None

    def clue_of(keys: list[str], t: int) -> int | None:
        for i, c in enumerate(clues):
            if c.start_sec - 15 <= t <= c.end_sec + 15 and hits(text(c), keys):
                return i
        return None

    print(f"단서 {len(clues)}개, 정답 장소 {len(places)}곳, 평가 문장 {len(utters)}개\n")

    # --- Bedrock ---
    gateway = GatewayChatInterpreter(
        "bedrock-haiku", api_key=env["LLM_API_KEY"].strip(), base_url=env["LLM_BASE_URL"].strip()
    )
    t0 = time.time()
    res = ChunkedInterpreter(gateway).interpret(obs, "compare")
    cands = res.result.candidates

    def name(c) -> str:
        return " ".join(c.names) + " " + (c.branch_hint or "")

    covered = [p for p in places if any(hits(name(c), p[1]) for c in cands)]
    split = [p for p in places if sum(hits(name(c), p[1]) for c in cands) >= 2]
    extra = [c for c in cands if not any(hits(name(c), p[1]) for p in places)]
    attached = right = 0
    for t, keys in utters:
        i, tp = clue_of(keys, t), truth(t)
        rated = [
            c
            for c in cands
            if i is not None
            and i in c.clue_refs
            and any(v != "NONE" for v in c.ratings.model_dump().values())
        ]
        attached += bool(rated)
        right += any(tp and hits(name(c), tp) for c in rated)
    status = [c.visit_status for c in cands]
    print(
        f"[Bedrock] 후보 {len(cands)}개 · 정답 장소 {len(covered)}/{len(places)}"
        f" · 한 장소가 둘 이상으로 갈라짐 {len(split)}곳"
    )
    print(f"          정답 밖 후보 {len(extra)}개: {[c.names[0] for c in extra][:14]}")
    print(
        f"          평가 붙음 {attached}/{len(utters)} · 올바른 장소에 붙음 {right}/{len(utters)}"
        f" · 방문 {status.count('VISITED')} / 언급 {status.count('MENTIONED')}"
        f" / 불명확 {status.count('UNCLEAR')}"
    )
    print(
        f"          {time.time() - t0:.0f}초 · 입력 {res.input_tokens:,}"
        f" · 출력 {res.output_tokens:,}\n"
    )

    # --- 규칙 기준선 ---
    def lines(c) -> list[str]:
        found = [c.heard_name] if c.heard_name else []
        if c.clue_type == "SCREEN_TEXT" and c.seen_text:
            found += c.seen_text.split("\n")
        return [s.strip() for s in found if 1 < len(s.strip()) <= 25]

    def pool(anchored: bool) -> list[tuple[int, str]]:
        items: list[tuple[int, str]] = []
        for c in clues:
            near_addr = any(
                ADDR.search(text(d))
                for d in clues
                if d is not c and abs(d.start_sec - c.start_sec) <= 10
            )
            if anchored and not near_addr and not c.heard_name:
                continue
            items += [(c.start_sec, s) for s in lines(c) if not (anchored and ADDR.search(s))]
        return items

    for label, anchored in (("모든 짧은 글자", False), ("주소 근처 글자 + 들린 이름", True)):
        items = pool(anchored)
        found = [p for p in places if any(hits(s, p[1]) for _, s in items)]
        ok = 0
        for t, keys in utters:
            i, tp = clue_of(keys, t), truth(t)
            prev = [(tm, s) for tm, s in items if i is not None and tm <= clues[i].start_sec]
            ok += bool(prev and tp and hits(max(prev)[1], tp))
        print(
            f"[규칙: {label}] 검색 후보 {len({norm(s) for _, s in items})}개"
            f" · 정답 장소 {len(found)}/{len(places)}"
            f" · 평가를 가장 가까운 앞쪽 글자에 붙여 올바른 장소 {ok}/{len(utters)}"
        )


if __name__ == "__main__":
    main()

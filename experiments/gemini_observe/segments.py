"""[2-2] 실험: 영상 하나를 N개 구간으로 나눠 동시에 관찰하고 결과를 합친다.

각 구간은 probe.py를 따로 실행한다(구간마다 Gemini 호출 1회). 합친 결과는 out/obs_<tag>.json에
써서 score.py·view.py가 그대로 읽는다. 시간은 가장 늦게 끝난 구간 기준.

  uv run python experiments/gemini_observe/segments.py --tag S1 --model gemini-3.5-flash-lite \\
      --video ec6YBcndc4w --duration 1121 --segments 4 --fps 0.5
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--video", required=True)
    p.add_argument("--duration", type=int, required=True)
    p.add_argument("--segments", type=int, default=4)
    p.add_argument("--fps", type=float, default=0.5)
    p.add_argument("--thinking", default="default")
    p.add_argument("--fallback", help="실패하거나 얇은 구간을 이 모델로 1회 더 보내 합친다")
    p.add_argument("--min-per-min", type=float, default=2.0, help="얇은 구간 기준: 1분당 단서 수")
    a = p.parse_args()

    step = -(-a.duration // a.segments)  # 올림
    bounds = [(i * step, min((i + 1) * step, a.duration)) for i in range(a.segments)]

    def start(tag: str, model: str, s: int, e: int) -> subprocess.Popen[str]:
        cmd = [sys.executable, str(HERE / "probe.py"), "--tag", tag]
        cmd += ["--model", model, "--video", a.video, "--duration", str(a.duration)]
        cmd += ["--res", "LOW", "--fps", str(a.fps), "--thinking", a.thinking]
        cmd += ["--clip", str(s), str(e)]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)

    def last_call(tag: str) -> dict:
        calls = [json.loads(line) for line in (OUT / "calls.jsonl").read_text().splitlines()]
        return next((r for r in reversed(calls) if r.get("tag") == tag), {})

    def result(tag: str) -> list[dict]:
        obs = OUT / f"obs_{tag}.json"
        if not obs.exists() or "input" not in last_call(tag):
            return []
        return json.loads(obs.read_text())["clues"]

    def thin(tag: str, s: int, e: int, median_out: float) -> bool:
        """실패, 1분당 단서 부족, 또는 출력이 다른 구간 중앙값의 1/4 미만이면 얇다."""
        out = last_call(tag).get("output") or 0
        few = len(result(tag)) < a.min_per_min * (e - s) / 60
        return few or out < median_out / 4

    # 1차: 모든 구간을 동시에
    t0 = time.time()
    tags = {i: [f"{a.tag}-{i + 1}"] for i in range(len(bounds))}
    for proc in [start(tags[i][0], a.model, *b) for i, b in enumerate(bounds)]:
        proc.communicate()
    ends = {i: time.time() - t0 for i in tags}

    # 2차: 실패·얇은 구간만 다른 모델로 동시에 한 번 더, 결과는 합친다
    outs = [last_call(tags[i][0]).get("output") or 0 for i in tags]
    median_out = sorted(outs)[len(outs) // 2]
    redo = [i for i, b in enumerate(bounds) if a.fallback and thin(tags[i][0], *b, median_out)]
    for i in redo:
        tags[i].append(f"{a.tag}-{i + 1}r")
    for proc in [start(tags[i][1], a.fallback, *bounds[i]) for i in redo]:
        proc.communicate()
    for i in redo:
        ends[i] = time.time() - t0

    clues, rows, seen = [], [], set()
    for i, (s, e) in enumerate(bounds):
        part = []
        for tag in tags[i]:
            rec = last_call(tag)
            got = result(tag)
            for c in got:  # 같은 시각(5초 단위)·같은 글자는 한 번만
                text = (c.get("seen_text") or c.get("utterance") or c.get("scene") or "")[:20]
                key = (c["start_sec"] // 5, c["clue_type"], text)
                if key not in seen:
                    seen.add(key)
                    part.append(c)
            rows.append(
                f"  {tag} {s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d} "
                f"{rec.get('model', '')[7:]} {rec.get('sec', '-')}초 단서 {len(got)} "
                f"{rec.get('error', '')[:40]}"
            )
        clues += part
    clues.sort(key=lambda c: c["start_sec"])
    (OUT / f"obs_{a.tag}.json").write_text(
        json.dumps({"video_id": a.video, "clues": clues}, ensure_ascii=False, indent=1)
    )
    slowest = max(ends.values())
    print(f"== {a.tag} {a.model} {a.segments}구간, 재요청 {len(redo)}: 끝 {slowest:.0f}초")
    print(f"   단서 {len(clues)}")
    print("\n".join(rows))


if __name__ == "__main__":
    main()

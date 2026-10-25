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
    a = p.parse_args()

    step = -(-a.duration // a.segments)  # 올림
    bounds = [(i * step, min((i + 1) * step, a.duration)) for i in range(a.segments)]
    t0 = time.time()
    procs = []
    for i, (s, e) in enumerate(bounds):
        cmd = [sys.executable, str(HERE / "probe.py"), "--tag", f"{a.tag}-{i + 1}"]
        cmd += ["--model", a.model, "--video", a.video, "--duration", str(a.duration)]
        cmd += ["--res", "LOW", "--fps", str(a.fps), "--thinking", a.thinking]
        cmd += ["--clip", str(s), str(e)]
        procs.append((i, time.time(), subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)))
    ends: dict[int, float] = {}
    for i, _, proc in procs:
        proc.communicate()
        ends[i] = time.time() - t0

    clues, rows = [], []
    calls = [json.loads(line) for line in (OUT / "calls.jsonl").read_text().splitlines()]
    for i, (s, e) in enumerate(bounds):
        tag = f"{a.tag}-{i + 1}"
        rec = next((r for r in reversed(calls) if r.get("tag") == tag), {})
        obs = OUT / f"obs_{tag}.json"
        part = json.loads(obs.read_text())["clues"] if obs.exists() and "input" in rec else []
        clues += part
        rows.append(
            f"  {tag} {s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d} "
            f"{rec.get('sec', '-')}초 단서 {len(part)} 출력 {rec.get('output', '-')} "
            f"{rec.get('error', '')[:60]}"
        )
    clues.sort(key=lambda c: c["start_sec"])
    (OUT / f"obs_{a.tag}.json").write_text(
        json.dumps({"video_id": a.video, "clues": clues}, ensure_ascii=False, indent=1)
    )
    slowest = max(ends.values())
    print(f"== {a.tag} {a.model} {a.segments}구간 동시: 가장 늦은 구간 {slowest:.0f}초")
    print(f"   단서 {len(clues)}")
    print("\n".join(rows))


if __name__ == "__main__":
    main()

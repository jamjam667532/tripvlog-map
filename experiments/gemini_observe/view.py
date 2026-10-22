"""관찰 결과를 영상 옆에 띄워 눈으로 확인하는 페이지를 만든다. Gemini 호출 없음.

  uv run python experiments/gemini_observe/view.py N6   # out/view_N6.html 생성 후 로컬 서버로 열기
  uv run python experiments/gemini_observe/view.py N6 --no-serve

단서를 누르면 그 재생 위치로 이동하고, 재생 중에는 현재 위치의 단서가 강조된다.
YouTube 임베드는 file://에서 막히므로 127.0.0.1에서 띄운다.
"""

import argparse
import functools
import html
import http.server
import json
import webbrowser
from pathlib import Path

OUT = Path(__file__).parent / "out"

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>관찰 {tag}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --mute:#78716c; --line:#e7e5e4; --hi:#fef3c7;
  --SPEECH:#2563eb; --SCREEN_TEXT:#16a34a; --SCENE:#9333ea; --warn:#dc2626; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1c1917; --fg:#f5f5f4; --mute:#a8a29e;
  --line:#44403c; --hi:#422006; }} }}
body {{ margin:0; font:14px/1.5 system-ui, sans-serif; background:var(--bg); color:var(--fg); }}
header {{ padding:12px 16px; border-bottom:1px solid var(--line); }}
header small {{ color:var(--mute); }}
main {{ display:grid; grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);
  height:calc(100vh - 58px); }}
#left {{ padding:16px; }}
#player {{ width:100%; aspect-ratio:16/9; }}
#list {{ overflow-y:auto; border-left:1px solid var(--line); }}
.c {{ padding:8px 16px; border-bottom:1px solid var(--line); cursor:pointer; }}
.c:hover {{ background:color-mix(in srgb, var(--hi) 50%, transparent); }}
.c.on {{ background:var(--hi); }}
.t {{ font-variant-numeric:tabular-nums; color:var(--mute); margin-right:6px; }}
.k {{ font-size:11px; font-weight:600; padding:1px 6px; border-radius:4px; color:#fff; }}
.u {{ font-size:11px; color:var(--warn); margin-left:6px; }}
.n {{ font-weight:600; }}
.f {{ display:flex; gap:12px; margin-top:12px; color:var(--mute); flex-wrap:wrap; }}
@media (max-width:800px) {{ main {{ grid-template-columns:1fr; height:auto; }}
  #list {{ border-left:0; }} }}
</style></head><body>
<header><b>Gemini 관찰 {tag}</b> <small>{meta}</small></header>
<main><div id="left"><div id="player"></div>
<div class="f"><label><input type="checkbox" id="follow" checked> 재생 위치 따라가기</label>
<span>{summary}</span></div></div>
<div id="list">{rows}</div></main>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
const clues = {clues};
let player;
function onYouTubeIframeAPIReady() {{
  player = new YT.Player("player", {{ videoId: {video}, playerVars: {{ start: {start} }} }});
}}
document.querySelectorAll(".c").forEach(el => el.onclick = () => {{
  if (player) {{ player.seekTo(+el.dataset.s, true); player.playVideo(); }}
}});
setInterval(() => {{
  if (!player || !player.getCurrentTime) return;
  const now = player.getCurrentTime();
  let first = null;
  document.querySelectorAll(".c").forEach((el, i) => {{
    const on = clues[i].start_sec - 1 <= now && now <= clues[i].end_sec + 1;
    el.classList.toggle("on", on);
    if (on && !first) first = el;
  }});
  if (first && document.getElementById("follow").checked)
    first.scrollIntoView({{ block: "nearest", behavior: "smooth" }});
}}, 500);
</script></body></html>
"""


def mmss(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


def row(c: dict) -> str:
    name = c.get("heard_name")
    body = " · ".join(
        html.escape(str(c[k])) for k in ("seen_text", "utterance", "scene") if c.get(k)
    )
    unc = "".join(f'<span class="u">{u}</span>' for u in c.get("uncertainty") or [])
    day = c.get("scene_daypart")
    return (
        f'<div class="c" data-s="{c["start_sec"]}">'
        f'<span class="t">{mmss(c["start_sec"])}-{mmss(c["end_sec"])}</span>'
        f'<span class="k" style="background:var(--{c["clue_type"]})">{c["clue_type"]}</span>'
        f"{unc}{f' <small>{day}</small>' if day and day != 'UNKNOWN' else ''}<br>"
        f"{f'<span class=n>들린 이름: {html.escape(name)}</span> ' if name else ''}{body}</div>"
    )


def build(tag: str) -> Path:
    obs = json.loads((OUT / f"obs_{tag}.json").read_text(encoding="utf-8"))
    clues = sorted(obs["clues"], key=lambda c: c["start_sec"])
    call = next(
        (
            json.loads(line)
            for line in reversed((OUT / "calls.jsonl").read_text(encoding="utf-8").splitlines())
            if json.loads(line).get("tag") == tag and "input" in json.loads(line)
        ),
        {},
    )
    meta = " · ".join(
        f"{k} {call[k]}"
        for k in ("model", "res", "fps", "clip", "sec", "input", "output", "thoughts")
        if call.get(k) not in (None, 0.0)
    )
    counts: dict[str, int] = {}
    for c in clues:
        counts[c["clue_type"]] = counts.get(c["clue_type"], 0) + 1
    page = PAGE.format(
        tag=html.escape(tag),
        meta=html.escape(meta),
        summary=html.escape(f"단서 {len(clues)}개 {counts}"),
        rows="".join(row(c) for c in clues),
        clues=json.dumps([{"start_sec": c["start_sec"], "end_sec": c["end_sec"]} for c in clues]),
        video=json.dumps(obs["video_id"]),
        start=clues[0]["start_sec"] if clues else 0,
    )
    path = OUT / f"view_{tag}.html"
    path.write_text(page, encoding="utf-8")
    return path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("tag")
    p.add_argument("--no-serve", action="store_true")
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    path = build(a.tag)
    print(path)
    if a.no_serve:
        return
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(OUT))
    with http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler) as srv:
        url = f"http://127.0.0.1:{a.port}/{path.name}"
        print(f"{url}  (Ctrl+C로 종료)")
        webbrowser.open(url)
        srv.serve_forever()


if __name__ == "__main__":
    main()

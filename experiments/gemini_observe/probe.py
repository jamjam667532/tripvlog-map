"""Gemini 관찰 실험 스크립트 (결정 0006, experiments/results/2026-10-21-gemini-observe.md).

실제 유료·무료 한도 API를 부른다. 한 번 실행에 Gemini 생성 호출 1회. 키는 출력하지 않는다.
키는 experiments/.env(GEMINI_API_KEY)에서 읽는다.
결과는 experiments/gemini_observe/out/에 저장한다(git 무시). 프롬프트는 prompt_v2.md.

예:
  uv run python experiments/gemini_observe/probe.py --tag P1 --video ec6YBcndc4w --duration 1121
  uv run python experiments/gemini_observe/probe.py --tag N5 --model gemini-3-flash-preview \\
      --video RE0k_4Ip_ns --duration 1113 --res HIGH --fps 0.5 --clip 270 540
  uv run python experiments/gemini_observe/probe.py --tag C1 --text-only   # 모델 응답 여부만 확인

출력 스키마는 재생 위치를 "MM:SS" 문자열로 받고(ClueWire), 초로 바꿔 기존 계약 ObservationResult로
검증한 뒤 out/obs_<tag>.json에 쓴다. 호출 기록은 out/calls.jsonl에 한 줄씩 남는다.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field, ValidationError  # noqa: E402

from shared.clients.ai_schema import ai_json_schema  # noqa: E402
from shared.schemas.observation import ObservationResult  # noqa: E402

OUT = Path(__file__).parent / "out"
TS = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):([0-5]\d)$")

# v2 + 대책 A 문장. 결정 0006 확정 시 backend/shared/prompts/observe.md로 옮긴다.
PROMPT = (Path(__file__).parent / "prompt_v2.md").read_text(encoding="utf-8")


class ClueWire(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start: str
    end: str
    clue_type: Literal["SPEECH", "SCREEN_TEXT", "SCENE"]
    heard_name: str | None = None
    seen_text: str | None = None
    utterance: str | None = None
    scene: str | None = None
    scene_daypart: Literal["DAY", "NIGHT", "UNKNOWN"] = "UNKNOWN"
    uncertainty: list[Literal["INAUDIBLE", "TEXT_UNCLEAR", "TARGET_AMBIGUOUS"]] = Field(
        default_factory=list
    )


class ObservationWire(BaseModel):
    model_config = ConfigDict(extra="ignore")
    video_id: str
    clues: list[ClueWire]


def to_sec(ts: str) -> int | None:
    m = TS.match(ts.strip())
    if not m:
        return None
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def load_key() -> str:
    for line in (ROOT / "experiments" / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("experiments/.env에 GEMINI_API_KEY가 없다")


def log(rec: dict[str, Any]) -> None:
    OUT.mkdir(exist_ok=True)
    with (OUT / "calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False)[:600])


def video_part(video: str, fps: float, clip: list[int] | None) -> types.Part:
    data = types.FileData(file_uri=f"https://www.youtube.com/watch?v={video}")
    if fps <= 0 and not clip:
        return types.Part(file_data=data)  # 기준선과 같은 방식(video_metadata 없음)
    meta = types.VideoMetadata(
        fps=fps if fps > 0 else None,
        start_offset=f"{clip[0]}s" if clip else None,
        end_offset=f"{clip[1]}s" if clip else None,
    )
    return types.Part(file_data=data, video_metadata=meta)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("--model", default="gemini-3.8-flash")
    p.add_argument("--video", default="ec6YBcndc4w")
    p.add_argument("--duration", type=int, default=1121, help="영상 길이(초). 재생 위치 검증용")
    p.add_argument("--res", choices=["LOW", "HIGH"], default="LOW")
    p.add_argument("--fps", type=float, default=0.0, help="0이면 지정 안 함(기본 1fps)")
    p.add_argument("--clip", type=int, nargs=2, metavar=("START", "END"), help="구간(초)")
    p.add_argument("--thinking", default="default", help="default | minimal | low | medium | high")
    p.add_argument("--text-only", action="store_true", help="짧은 텍스트로 모델 응답 여부만 확인")
    a = p.parse_args()

    client = genai.Client(api_key=load_key())
    rec: dict[str, Any] = {"tag": a.tag, "model": a.model, "at": time.strftime("%Y-%m-%d %H:%M")}
    t0 = time.time()

    if a.text_only:
        try:
            r = client.models.generate_content(model=a.model, contents="한 단어로 답해: 안녕")
            rec.update(text_ok=True, total=r.usage_metadata.total_token_count)
        except Exception as e:
            rec.update(text_ok=False, error=f"{type(e).__name__} {str(e)[:150]}")
        log(rec)
        return

    rec.update(video=a.video, res=a.res, fps=a.fps, clip=a.clip, thinking=a.thinking)
    cfg: dict[str, Any] = dict(
        system_instruction=PROMPT,
        temperature=0.0,
        response_mime_type="application/json",
        response_json_schema=ai_json_schema(ObservationWire),
        media_resolution=types.MediaResolution(f"MEDIA_RESOLUTION_{a.res}"),
        http_options=types.HttpOptions(timeout=600_000),
    )
    if a.thinking != "default":
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=a.thinking)
    contents = types.Content(
        role="user",
        parts=[video_part(a.video, a.fps, a.clip), types.Part(text=f"video_id: {a.video}")],
    )
    try:
        resp = client.models.generate_content(
            model=a.model, contents=contents, config=types.GenerateContentConfig(**cfg)
        )
    except Exception as e:
        rec.update(error=f"{type(e).__name__} {str(e)[:200]}", sec=round(time.time() - t0))
        log(rec)
        return

    u = resp.usage_metadata
    rec.update(
        sec=round(time.time() - t0),
        input=u.prompt_token_count,
        output=u.candidates_token_count,
        thoughts=u.thoughts_token_count or 0,
        total=u.total_token_count,
    )
    text = resp.text or ""
    OUT.mkdir(exist_ok=True)
    (OUT / f"raw_{a.tag}.txt").write_text(text, encoding="utf-8")
    try:
        wire = ObservationWire.model_validate_json(text)
        converted, bad_ts, out_of_range = [], 0, 0
        for c in wire.clues:
            s, e = to_sec(c.start), to_sec(c.end)
            if s is None or e is None:
                bad_ts += 1
                continue
            if s > a.duration or e > a.duration or e < s:
                out_of_range += 1
            item = c.model_dump(exclude={"start", "end"})
            converted.append({**item, "start_sec": s, "end_sec": max(e, s)})
        final = ObservationResult.model_validate({"video_id": a.video, "clues": converted})
        (OUT / f"obs_{a.tag}.json").write_text(final.model_dump_json(indent=2), encoding="utf-8")
        rec.update(
            schema_ok=True, clues=len(wire.clues), bad_timestamp=bad_ts, out_of_range=out_of_range
        )
    except ValidationError as e:
        rec.update(schema_ok=False, schema_error=str(e)[:200])
    log(rec)


if __name__ == "__main__":
    main()

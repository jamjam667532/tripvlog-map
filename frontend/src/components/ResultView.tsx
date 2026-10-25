import { useEffect, useMemo, useRef, useState } from "react";

import type { JobResult } from "../types";
import MapPanel from "./MapPanel";
import PlaceCard from "./PlaceCard";

interface Props {
  result: JobResult;
  demo: boolean;
  onReset: () => void;
}

const ALL = "전체";

export default function ResultView({ result, demo, onReset }: Props) {
  const [area, setArea] = useState(ALL);
  const [showUnconfirmed, setShowUnconfirmed] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const cardRefs = useRef(new Map<string, HTMLLIElement>());

  const sorted = useMemo(() => [...result.places].sort((a, b) => a.rank - b.rank), [result.places]);
  const areas = useMemo(
    () => [ALL, ...new Set(sorted.map((p) => p.areaGroup).filter((a): a is string => !!a))],
    [sorted],
  );
  const visible = useMemo(() => (area === ALL ? sorted : sorted.filter((p) => p.areaGroup === area)), [sorted, area]);

  // 채널 ID 대신 "채널 A, B…"로 표시 (채널명은 저장하지 않는다)
  const channelLabel = useMemo(() => {
    const order = new Map<string, string>();
    sorted.forEach((p) =>
      p.evidence.forEach((e) => {
        if (!order.has(e.channelId)) order.set(e.channelId, `채널 ${String.fromCharCode(65 + order.size)}`);
      }),
    );
    return (id: string) => order.get(id) ?? "채널";
  }, [sorted]);

  useEffect(() => {
    if (selectedId) cardRefs.current.get(selectedId)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedId]);

  const select = (id: string) => setSelectedId((cur) => (cur === id ? null : id));

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <aside className="flex min-h-0 flex-col border-stone-200 lg:w-[440px] lg:shrink-0 lg:border-r">
        <div className="flex flex-col gap-3 border-b border-stone-200 bg-white p-4">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-xl font-bold text-[#14213D]">{result.destination}</h2>
            <button type="button" onClick={onReset} className="text-sm text-stone-500 underline hover:text-stone-800">
              새로 검색
            </button>
          </div>
          <p className="text-sm text-stone-600">
            분석 성공 {result.analyzedChannels}개 채널 · 장소 {result.places.length}곳
            {result.failedVideos ? ` · 분석 실패 영상 ${result.failedVideos}개` : ""}
          </p>
          {demo && (
            <p className="rounded-lg bg-[#FBE3D3] px-3 py-2 text-xs text-[#7a3210]">
              시연용 예시 결과입니다. 실제 Gemini 관찰(오사카 영상 5개)의 재생 위치·원문을 옮기고 집계는 손으로
              정리했습니다. 좌표는 근사값입니다.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {areas.map((a) => (
              <button
                key={a}
                type="button"
                aria-pressed={area === a}
                onClick={() => setArea(a)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  area === a ? "border-[#14213D] bg-[#14213D] text-white" : "border-stone-300 bg-white text-stone-700"
                }`}
              >
                {a}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm text-stone-700">
            <input type="checkbox" checked={showUnconfirmed} onChange={(e) => setShowUnconfirmed(e.target.checked)} />
            미확정 후보 보기 ({result.unconfirmed.length})
          </label>
        </div>

        <ol className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto bg-[#F7F5F0] p-4">
          {visible.map((p) => (
            <PlaceCard
              key={p.placeId}
              ref={(el) => {
                if (el) cardRefs.current.set(p.placeId, el);
                else cardRefs.current.delete(p.placeId);
              }}
              place={p}
              selected={p.placeId === selectedId}
              channelLabel={channelLabel}
              onSelect={() => select(p.placeId)}
            />
          ))}
          {visible.length === 0 && <li className="p-4 text-center text-sm text-stone-500">확정된 장소가 없습니다</li>}

          {showUnconfirmed && (
            <li className="rounded-xl border border-dashed border-stone-300 bg-white p-4 text-sm">
              <p className="mb-2 font-semibold text-stone-700">미확정 후보 · 지점이 하나로 좁혀지지 않아 지도에 표시하지 않음</p>
              <ul className="flex flex-col gap-1 text-stone-600">
                {result.unconfirmed.map((u) => (
                  <li key={u.names.join("|")}>{u.names.join(" / ")} · 여러 지점</li>
                ))}
                {result.unconfirmed.length === 0 && <li>없음</li>}
              </ul>
            </li>
          )}
        </ol>
      </aside>

      <div className="order-first h-[45vh] shrink-0 lg:order-last lg:h-auto lg:min-h-0 lg:flex-1">
        <MapPanel places={visible} selectedId={selectedId} onSelect={select} />
      </div>
    </div>
  );
}

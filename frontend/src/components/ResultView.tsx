import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CATEGORY_LABEL, thumbnailUrl } from "../format";
import { acknowledge, advanceLive, initLive, needsAdvance, rankOrder, sortByRank, type LiveState } from "../liveResult";
import type { Category, JobResult, ResultStage, VideoProgress } from "../types";
import { SegmentCells } from "./JobProgress";
import MapPanel from "./MapPanel";
import PlaceCard from "./PlaceCard";

interface Props {
  result: JobResult;
  stage: ResultStage | undefined; // 없으면 최종 결과로 본다
  videos: VideoProgress[];
  demo: boolean;
  onReset: () => void;
}

const ALL = "전체";
const TABS: (Category | typeof ALL)[] = [ALL, "RESTAURANT", "CAFE", "ATTRACTION"];

function LiveStrip({ videos }: { videos: VideoProgress[] }) {
  return (
    <ul className="flex gap-2 overflow-x-auto pb-1" aria-label="영상별 진행">
      {videos.map((v, i) => (
        <li key={v.videoId} className="flex w-32 shrink-0 flex-col gap-1">
          <img src={thumbnailUrl(v.videoId)} alt="" className="h-[72px] w-32 rounded-md bg-stone-200 object-cover" />
          <span className="truncate text-xs text-stone-600">{v.channelTitle ?? `영상 ${i + 1}`}</span>
          {v.segments && <SegmentCells segments={v.segments} />}
          <span className={`text-xs ${v.quality === "PREVIEW" ? "text-sky-700" : "text-stone-500"}`}>
            {v.state === "FAILED" ? "실패" : v.quality === "PREVIEW" ? "평가 보강 중" : v.state === "DONE" ? "완료" : "분석 중"}
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function ResultView({ result, stage, videos, demo, onReset }: Props) {
  const live = stage === "PARTIAL_LIVE";
  const [area, setArea] = useState(ALL);
  const [tab, setTab] = useState<Category | typeof ALL>(ALL);
  const [showUnconfirmed, setShowUnconfirmed] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const cardRefs = useRef(new Map<string, HTMLLIElement>());

  // 새 응답이 오면 보던 순서를 지키면서 반영한다(렌더 중 파생 상태 갱신)
  const [state, setState] = useState<LiveState>(() => initLive(result.places, stage));
  if (needsAdvance(state, result.places, stage)) setState(advanceLive(state, result.places, stage));

  const byId = useMemo(() => new Map(result.places.map((p) => [p.placeId, p])), [result.places]);
  const ordered = useMemo(
    () => state.order.map((id) => byId.get(id)).filter((p) => p !== undefined),
    [state.order, byId],
  );
  const areas = useMemo(
    () => [ALL, ...new Set(ordered.map((p) => p.areaGroup).filter((a): a is string => !!a))],
    [ordered],
  );
  const visible = useMemo(
    () => ordered.filter((p) => (area === ALL || p.areaGroup === area) && (tab === ALL || p.category === tab)),
    [ordered, area, tab],
  );
  const freshIds = useMemo(() => new Set(state.fresh), [state.fresh]);
  const outOfRank = state.order.join() !== rankOrder(result.places).join();

  // 근거 링크에 채널 이름(응답에 있으면) 또는 "채널 A, B…"
  const channelLabel = useMemo(() => {
    const byVideo = new Map(videos.filter((v) => v.channelTitle).map((v) => [v.videoId, v.channelTitle!]));
    const channels = [...new Set(result.places.flatMap((p) => p.evidence.map((e) => e.channelId)))];
    const letters = new Map(channels.map((c, i) => [c, `채널 ${String.fromCharCode(65 + i)}`]));
    return (videoId: string, channelId: string) => byVideo.get(videoId) ?? letters.get(channelId) ?? "채널";
  }, [videos, result.places]);

  useEffect(() => {
    if (selectedId) cardRefs.current.get(selectedId)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedId]);

  const select = useCallback((id: string) => setSelectedId((cur) => (cur === id ? null : id)), []);

  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <aside className="flex min-h-0 flex-col border-stone-200 lg:w-[460px] lg:shrink-0 lg:border-r">
        <div className="flex flex-col gap-3 border-b border-stone-200 bg-white p-4">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-xl font-bold text-[#14213D]">
              {result.destination}{" "}
              <span className={`text-sm font-semibold ${live ? "text-amber-700" : "text-emerald-700"}`}>
                {live ? "분석 중" : "완료"}
              </span>
            </h2>
            <button type="button" onClick={onReset} className="text-sm text-stone-500 underline hover:text-stone-800">
              새로 검색
            </button>
          </div>
          <p className="text-sm text-stone-600">
            {live ? "지금까지" : "분석 성공"} {result.analyzedChannels}개 채널 · 장소 {result.places.length}곳
            {result.failedVideos ? ` · 분석 실패 영상 ${result.failedVideos}개` : ""}
          </p>
          {live && videos.length > 0 && <LiveStrip videos={videos} />}
          {demo && (
            <p className="rounded-lg bg-[#FBE3D3] px-3 py-2 text-xs text-[#7a3210]">
              시연용 예시 결과입니다. 실제 Gemini 관찰(오사카 영상 5개)의 재생 위치·원문을 옮기고 집계·단계는 손으로
              흉내 냈습니다. 좌표는 근사값입니다.
            </p>
          )}

          <div className="flex gap-1 rounded-lg bg-stone-100 p-1" role="tablist" aria-label="분류">
            {TABS.map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={`flex-1 rounded-md px-2 py-1 text-sm ${tab === t ? "bg-white font-semibold shadow-sm" : "text-stone-600"}`}
              >
                {t === ALL ? ALL : CATEGORY_LABEL[t]}
              </button>
            ))}
          </div>
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
          <div className="flex items-center justify-between gap-2">
            <label className="flex items-center gap-2 text-sm text-stone-700">
              <input type="checkbox" checked={showUnconfirmed} onChange={(e) => setShowUnconfirmed(e.target.checked)} />
              미확정 후보 보기 ({result.unconfirmed.length})
            </label>
            {outOfRank && (
              <button
                type="button"
                onClick={() => setState(sortByRank)}
                className="text-xs text-[#2D5BA8] underline"
              >
                순위대로 정렬
              </button>
            )}
          </div>
        </div>

        {state.newRatings > 0 && (
          <button
            type="button"
            onClick={() => setState(acknowledge)}
            className="bg-[#2D5BA8] px-4 py-2 text-left text-sm font-semibold text-white"
          >
            새 평가 {state.newRatings}개가 반영됐어요 · 확인
          </button>
        )}

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
              fresh={freshIds.has(p.placeId)}
              live={live}
              channelLabel={channelLabel}
              onSelect={select}
            />
          ))}
          {visible.length === 0 && (
            <li className="p-4 text-center text-sm text-stone-500">
              {live ? "확정된 장소가 아직 없습니다" : "확정된 장소가 없습니다"}
            </li>
          )}

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
        <MapPanel
          places={visible}
          selectedId={selectedId}
          freshIds={freshIds}
          fitKey={`${area}|${tab}`}
          onSelect={select}
        />
      </div>
    </div>
  );
}

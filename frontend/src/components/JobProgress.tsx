import { VIDEO_STATE_LABEL } from "../format";
import type { GetJobResponse, VideoState } from "../types";

interface Props {
  job: GetJobResponse | undefined;
  timedOut: boolean;
  onReset: () => void;
}

const BADGE: Record<VideoState, string> = {
  PENDING: "bg-stone-100 text-stone-600",
  ANALYZING: "bg-amber-100 text-amber-800 animate-pulse",
  DONE: "bg-emerald-100 text-emerald-800",
  FAILED: "bg-red-100 text-red-700",
  SKIPPED: "bg-stone-100 text-stone-500",
};

export default function JobProgress({ job, timedOut, onReset }: Props) {
  const total = job?.progress.total ?? 0;
  const done = (job?.progress.analyzed ?? 0) + (job?.progress.failed ?? 0);
  const pct = total ? Math.round((done / total) * 100) : 0;

  return (
    <section className="mx-auto flex w-full max-w-xl flex-col gap-6 rounded-2xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8">
      <div className="flex flex-col gap-1">
        <h2 className="text-xl font-bold text-[#14213D]">영상을 분석하고 있어요</h2>
        <p className="text-sm text-stone-500">영상마다 관찰(Gemini) → 해석(Bedrock) → 지점 매칭 순서로 진행됩니다</p>
      </div>

      <div className="flex flex-col gap-2">
        <div
          className="h-3 overflow-hidden rounded-full bg-stone-100"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-label="분석 진행률"
        >
          <div className="h-full rounded-full bg-[#E2703A] transition-all duration-700" style={{ width: `${pct}%` }} />
        </div>
        <p className="text-sm text-stone-600">
          {total ? `${total}개 중 ${done}개 처리` : "작업 접수됨 · 영상 수집 중"}
          {job?.progress.failed ? ` · 실패 ${job.progress.failed}개` : ""}
        </p>
      </div>

      {job && job.videos.length > 0 && (
        <ul className="flex flex-col divide-y divide-stone-100 rounded-xl border border-stone-200">
          {job.videos.map((v, i) => (
            <li key={v.videoId} className="flex items-center justify-between px-4 py-3">
              <span className="text-sm text-stone-700">
                영상 {i + 1} <span className="font-mono text-xs text-stone-400">{v.videoId}</span>
              </span>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${BADGE[v.state]}`}>
                {VIDEO_STATE_LABEL[v.state]}
              </span>
            </li>
          ))}
        </ul>
      )}

      {timedOut && (
        <p role="status" className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
          분석이 예상보다 오래 걸리고 있어요(10분 초과). 잠시 후 다시 확인하거나 새로 검색해 주세요.
        </p>
      )}

      <button type="button" onClick={onReset} className="self-start text-sm text-stone-500 underline hover:text-stone-800">
        새로 검색
      </button>
    </section>
  );
}

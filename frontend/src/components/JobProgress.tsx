import { thumbnailUrl, VIDEO_STATE_LABEL } from "../format";
import type { GetJobResponse, VideoProgress, VideoState } from "../types";

interface Props {
  job: GetJobResponse | undefined;
  timedOut: boolean;
  onReset: () => void;
}

const BADGE: Record<VideoState, string> = {
  PENDING: "bg-stone-100 text-stone-600",
  ANALYZING: "bg-amber-100 text-amber-800",
  DONE: "bg-emerald-100 text-emerald-800",
  FAILED: "bg-red-100 text-red-700",
  SKIPPED: "bg-stone-100 text-stone-500",
};

/** 구간 진행 칸 (done/total). 구간은 동시에 분석되므로 위치 대신 끝난 칸 수만 보여 준다. */
export function SegmentCells({ segments }: { segments: NonNullable<VideoProgress["segments"]> }) {
  return (
    <div className="flex gap-1" role="img" aria-label={`구간 ${segments.total}개 중 ${segments.done}개 분석`}>
      {Array.from({ length: segments.total }, (_, i) => (
        <span
          key={i}
          className={`h-1.5 flex-1 rounded-full transition-colors duration-500 ${
            i < segments.done ? "bg-[#E2703A]" : "bg-stone-200"
          }`}
        />
      ))}
    </div>
  );
}

export function VideoCard({ video, index }: { video: VideoProgress; index: number }) {
  return (
    <li className="flex gap-3 rounded-xl border border-stone-200 bg-white p-3">
      <img
        src={thumbnailUrl(video.videoId)}
        alt=""
        className="h-16 w-28 shrink-0 rounded-md bg-stone-200 object-cover"
        loading="lazy"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex items-start justify-between gap-2">
          <p className="line-clamp-2 text-sm font-semibold text-stone-800">{video.title ?? `영상 ${index + 1}`}</p>
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE[video.state]}`}>
            {video.state === "DONE" && video.quality === "PREVIEW" ? "미리보기" : VIDEO_STATE_LABEL[video.state]}
          </span>
        </div>
        <p className="text-xs text-stone-500">
          {video.channelTitle ?? ""} <span className="font-mono text-stone-400">{video.videoId}</span>
        </p>
        {video.segments && <SegmentCells segments={video.segments} />}
        {video.previewNames && video.previewNames.length > 0 && (
          <ul className="flex flex-wrap gap-1" aria-label="확인 중인 장소 이름">
            {video.previewNames.map((n) => (
              <li key={n} className="rounded-full border border-dashed border-stone-300 px-2 py-0.5 text-xs text-stone-500">
                {n} <span className="text-stone-400">· 확인 중</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

export default function JobProgress({ job, timedOut, onReset }: Props) {
  const videos = job?.videos ?? [];
  const total = job?.progress.total ?? 0;
  const done = (job?.progress.analyzed ?? 0) + (job?.progress.failed ?? 0);

  return (
    <section className="mx-auto flex w-full max-w-2xl flex-col gap-5 rounded-2xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8">
      <div className="flex flex-col gap-1">
        <h2 className="text-xl font-bold text-[#14213D]">
          {videos.length ? "영상을 분석하고 있어요" : "브이로그를 고르고 있어요"}
        </h2>
        <p className="text-sm text-stone-500">
          {total
            ? `${total}개 중 ${done}개 완료 · 관찰(Gemini) → 해석(Bedrock) → 지점 매칭`
            : "서로 다른 채널의 한국어 브이로그를 찾는 중"}
          {job?.progress.failed ? ` · 실패 ${job.progress.failed}개` : ""}
        </p>
      </div>

      {videos.length > 0 && (
        <ul className="flex flex-col gap-2">
          {videos.map((v, i) => (
            <VideoCard key={v.videoId} video={v} index={i} />
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

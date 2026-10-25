import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api as defaultApi, ApiError, type Api } from "./api";
import JobForm from "./components/JobForm";
import JobProgress from "./components/JobProgress";
import ResultView from "./components/ResultView";
import { clearGuestJob, loadGuestJob, saveGuestJob, type GuestJob } from "./session";
import { TERMINAL_STATUSES, type CreateJobRequest } from "./types";

const POLL_MS = 2000; // 진행 중 결과를 단계적으로 받는다(메모 답장 2번)
const MAX_WAIT_MS = 10 * 60 * 1000;

export default function App({ api = defaultApi }: { api?: Api }) {
  const [guestJob, setGuestJob] = useState<GuestJob | null>(() => loadGuestJob());
  const [startedAt, setStartedAt] = useState(() => Date.now());
  const [timedOut, setTimedOut] = useState(false);

  const create = useMutation({
    mutationFn: (req: Omit<CreateJobRequest, "requestId">) =>
      api.createJob({ ...req, requestId: crypto.randomUUID() }),
    onSuccess: (res) => {
      const job = { jobId: res.jobId, guestAccessToken: res.guestAccessToken };
      saveGuestJob(job);
      setGuestJob(job);
      setStartedAt(Date.now());
      setTimedOut(false);
    },
  });

  const job = useQuery({
    queryKey: ["job", guestJob?.jobId],
    enabled: !!guestJob,
    queryFn: async () => {
      try {
        return await api.getJob(guestJob!.jobId, guestJob!.guestAccessToken);
      } catch (err) {
        // 토큰 불일치·만료(404)면 저장된 작업을 버린다
        if (err instanceof ApiError && err.status === 404) clearGuestJob();
        throw err;
      }
    },
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      if (status && TERMINAL_STATUSES.includes(status)) return false;
      return timedOut ? false : POLL_MS;
    },
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });

  const notFound = job.error instanceof ApiError && job.error.status === 404;
  const status = job.data?.status;
  const terminal = !!status && TERMINAL_STATUSES.includes(status);

  useEffect(() => {
    if (!guestJob || terminal) return;
    const t = setTimeout(() => setTimedOut(true), Math.max(0, startedAt + MAX_WAIT_MS - Date.now()));
    return () => clearTimeout(t);
  }, [guestJob, terminal, startedAt]);

  const reset = () => {
    clearGuestJob();
    setGuestJob(null);
    setTimedOut(false);
    create.reset();
  };

  const createError =
    create.error instanceof ApiError && create.error.status === 429
      ? "오늘 분석 요청이 많아요. 잠시 후 다시 시도해 주세요."
      : create.error
        ? "작업을 접수하지 못했습니다. 다시 시도해 주세요."
        : notFound
          ? "작업을 찾을 수 없습니다. 다시 검색해 주세요."
          : null;

  const result = job.data?.result;

  return (
    <div className="flex h-dvh flex-col bg-[#F7F5F0] text-stone-900">
      <header className="flex items-center justify-between border-b border-stone-200 bg-[#14213D] px-4 py-3 text-white sm:px-6">
        <button type="button" onClick={reset} className="flex items-baseline gap-2 text-left">
          <h1 className="text-lg font-black tracking-tight">tripvlog-map</h1>
          <span className="hidden text-xs text-[#C9D1E0] sm:inline">여행 브이로그 근거 지도</span>
        </button>
        {api.mode === "mock" && <span className="rounded bg-[#E2703A] px-2 py-0.5 text-xs font-bold">시연 모드</span>}
      </header>

      {!guestJob || notFound ? (
        <main className="flex flex-1 flex-col items-center justify-center gap-6 overflow-y-auto px-4 py-10">
          <div className="max-w-xl text-center">
            <p className="text-2xl font-black text-[#14213D] sm:text-3xl">목적지만 입력하세요</p>
            <p className="mt-2 text-stone-600">
              한국어 여행 브이로그를 자동으로 골라, 여러 채널이 실제로 방문한 장소를 근거와 함께 지도에 보여드려요.
            </p>
          </div>
          <JobForm onSubmit={(req) => create.mutate(req)} submitting={create.isPending} error={createError} />
        </main>
      ) : result ? (
        <ResultView
          result={result}
          stage={job.data?.resultStage}
          videos={job.data?.videos ?? []}
          demo={api.mode === "mock"}
          onReset={reset}
        />
      ) : terminal ? (
        <main className="flex flex-1 flex-col items-center justify-center gap-4 px-4">
          <p className="text-lg font-bold text-[#14213D]">분석에 실패했습니다</p>
          <button type="button" onClick={reset} className="rounded-xl bg-[#E2703A] px-5 py-2 font-bold text-white">
            새로 검색
          </button>
        </main>
      ) : (
        <main className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 py-10">
          <JobProgress job={job.data} timedOut={timedOut} onReset={reset} />
        </main>
      )}
    </div>
  );
}

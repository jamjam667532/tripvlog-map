// 백엔드 배포 전 시연용 가짜 API. 영상 5개를 차례로 분석하는 것처럼 상태를 바꾼 뒤 결과를 돌려준다.
import type { Api } from "../api";
import type { GetJobResponse, VideoState } from "../types";
import { DEMO_VIDEO_IDS, osakaDemoResult } from "./osakaDemo";

interface MockJob {
  createdAt: number;
}

function randomToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** 영상 하나당 stepMs 동안 ANALYZING, 그다음 DONE. 모두 끝나면 SUCCEEDED. */
export function createMockApi({ stepMs = 2500, now = () => Date.now() } = {}): Api {
  const jobs = new Map<string, MockJob>();

  return {
    mode: "mock",
    async createJob() {
      const jobId = crypto.randomUUID();
      jobs.set(jobId, { createdAt: now() });
      return { jobId, guestAccessToken: randomToken(), status: "QUEUED" };
    },
    async getJob(jobId): Promise<GetJobResponse> {
      // 새로고침으로 메모리가 비면 끝난 작업으로 본다
      const job = jobs.get(jobId) ?? { createdAt: 0 };
      const step = stepMs > 0 ? Math.floor((now() - job.createdAt) / stepMs) : Infinity;
      const total = DEMO_VIDEO_IDS.length;
      const analyzed = Math.min(Math.max(step, 0), total);
      const videos = DEMO_VIDEO_IDS.map((videoId, i) => {
        const state: VideoState = i < analyzed ? "DONE" : i === analyzed ? "ANALYZING" : "PENDING";
        return { videoId, state };
      });
      const done = analyzed >= total;
      return {
        jobId,
        status: done ? "SUCCEEDED" : step <= 0 ? "QUEUED" : "RUNNING",
        progress: { total, analyzed, failed: 0 },
        videos,
        result: done ? osakaDemoResult(jobId) : null,
      };
    },
  };
}

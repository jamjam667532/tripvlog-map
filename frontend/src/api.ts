// API 호출은 여기에만. VITE_API_BASE가 있으면 실제 /public/jobs, 없으면 시연용 가짜 API.
import { createMockApi } from "./mock/mockApi";
import type { ApiErrorBody, CreateJobRequest, CreateJobResponse, GetJobResponse } from "./types";

export interface Api {
  readonly mode: "http" | "mock";
  createJob(req: CreateJobRequest): Promise<CreateJobResponse>;
  getJob(jobId: string, guestAccessToken: string): Promise<GetJobResponse>;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly jobId?: string,
  ) {
    super(message);
  }
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    return new ApiError(res.status, body.error.code, body.error.message, body.jobId);
  } catch {
    return new ApiError(res.status, "HTTP_ERROR", `요청 실패 (${res.status})`);
  }
}

export function createHttpApi(base: string): Api {
  const root = base.replace(/\/+$/, "");
  return {
    mode: "http",
    async createJob(req) {
      const res = await fetch(`${root}/public/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (res.status !== 202) throw await parseError(res);
      return (await res.json()) as CreateJobResponse;
    },
    async getJob(jobId, guestAccessToken) {
      const res = await fetch(`${root}/public/jobs/${encodeURIComponent(jobId)}`, {
        headers: { "X-Guest-Access-Token": guestAccessToken },
      });
      if (!res.ok) throw await parseError(res);
      return (await res.json()) as GetJobResponse;
    },
  };
}

const base = import.meta.env.VITE_API_BASE as string | undefined;

export const api: Api = base ? createHttpApi(base) : createMockApi();

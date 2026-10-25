import { describe, expect, it } from "vitest";

import { createMockApi } from "./mockApi";

describe("createMockApi", () => {
  it("영상을 차례로 분석한 뒤 SUCCEEDED와 결과를 돌려준다", async () => {
    let t = 0;
    const api = createMockApi({ stepMs: 1000, now: () => t });
    const { jobId, guestAccessToken, status } = await api.createJob({
      requestId: "r",
      destination: "오사카",
      styles: [],
      companion: null,
    });
    expect(status).toBe("QUEUED");
    expect(guestAccessToken).toMatch(/^[A-Za-z0-9_-]{43}$/);

    let job = await api.getJob(jobId, guestAccessToken);
    expect(job.status).toBe("QUEUED");
    expect(job.videos[0].state).toBe("ANALYZING");
    expect(job.result).toBeNull();

    t = 2500;
    job = await api.getJob(jobId, guestAccessToken);
    expect(job.status).toBe("RUNNING");
    expect(job.progress.analyzed).toBe(2);
    expect(job.videos.map((v) => v.state)).toEqual(["DONE", "DONE", "ANALYZING", "PENDING", "PENDING"]);

    t = 5000;
    job = await api.getJob(jobId, guestAccessToken);
    expect(job.status).toBe("SUCCEEDED");
    expect(job.result?.places.length).toBeGreaterThan(0);
  });

  it("결과의 방문 채널 수는 분모를 넘지 않는다", async () => {
    const api = createMockApi({ stepMs: 1, now: () => 1e9 });
    const job = await api.getJob("unknown", "t");
    const result = job.result!;
    for (const p of result.places) {
      expect(p.channels.visited).toBeLessThanOrEqual(p.channels.denominator);
      expect(p.channels.denominator).toBe(result.analyzedChannels);
    }
  });
});

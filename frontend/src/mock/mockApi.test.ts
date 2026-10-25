import { describe, expect, it } from "vitest";

import { createMockApi, STAGE } from "./mockApi";

const REQ = { requestId: "r", destination: "오사카", styles: [], companion: null };

describe("createMockApi (단계적 결과 흉내)", () => {
  it("영상 고름 → 구간 진행·확인 중 칩 → 1차 결과 → 보강 → FINAL 순서로 바뀐다", async () => {
    let t = 0; // 논리 초 = ms (secondMs: 1)
    const api = createMockApi({ secondMs: 1, now: () => t });
    const { jobId, guestAccessToken, status } = await api.createJob(REQ);
    expect(status).toBe("QUEUED");
    expect(guestAccessToken).toMatch(/^[A-Za-z0-9_-]{43}$/);

    let job = await api.getJob(jobId, guestAccessToken);
    expect(job.videos).toEqual([]);
    expect(job.result).toBeNull();

    t = 15;
    job = await api.getJob(jobId, guestAccessToken);
    expect(job.status).toBe("RUNNING");
    expect(job.videos).toHaveLength(5);
    expect(job.videos.every((v) => v.state === "ANALYZING")).toBe(true);
    expect(job.videos[0].segments!.done).toBeGreaterThan(0);
    expect(job.videos[0].segments!.done).toBeLessThan(6);
    expect(job.videos.some((v) => (v.previewNames ?? []).length > 0)).toBe(true);
    expect(job.result).toBeNull();

    t = STAGE.firstResult;
    job = await api.getJob(jobId, guestAccessToken);
    expect(job.resultStage).toBe("PARTIAL_LIVE");
    const first = job.result!;
    const pending = first.places.filter((p) => p.pendingEnrichment);
    expect(pending.length).toBeGreaterThan(0);
    expect(pending.every((p) => Object.keys(p.ratings).length === 0 && p.revision === 0)).toBe(true);
    expect(job.videos.map((v) => v.quality)).toEqual(["FULL", "FULL", "PREVIEW", "PREVIEW", "PREVIEW"]);

    t = 60;
    job = await api.getJob(jobId, guestAccessToken);
    const enriched = job.result!.places.filter((p) => p.revision === 1).length;
    expect(enriched).toBeGreaterThan(first.places.filter((p) => p.revision === 1).length);

    t = STAGE.final;
    job = await api.getJob(jobId, guestAccessToken);
    expect(job.status).toBe("SUCCEEDED");
    expect(job.resultStage).toBe("FINAL");
    expect(job.result!.places.every((p) => !p.pendingEnrichment)).toBe(true);
  });

  it("결과의 방문 채널 수는 분모를 넘지 않는다", async () => {
    const api = createMockApi({ secondMs: 0 });
    const result = (await api.getJob("unknown", "t")).result!;
    for (const p of result.places) {
      expect(p.channels.visited).toBeLessThanOrEqual(p.channels.denominator);
      expect(p.channels.denominator).toBe(result.analyzedChannels);
    }
  });
});

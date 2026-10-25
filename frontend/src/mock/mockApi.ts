// 백엔드 배포 전 시연용 가짜 API. 단계적 결과 화면(docs/memo-frontend-progressive-ui-reply.md)을 흉내 낸다.
//
// 논리 시각(초) 기준 단계. 실제 시간은 secondMs배(기본 250ms → 150초가 약 38초).
//   0~3   영상 고르는 중 (videos 없음)
//   3~30  영상마다 구간 6개 분석, 찾은 이름 칩이 쌓임
//   30    1차 결과(PARTIAL_LIVE). 영상 1·2는 FULL, 3~5는 미리보기 → 그 장소는 "평가 보강 중"
//   60    영상 3·4 보강, 120 영상 5 보강
//   150   FINAL (순위 확정)
import type { Api } from "../api";
import type { GetJobResponse, JobResult, ResultPlace, VideoProgress, VideoQuality } from "../types";
import { DEMO_VIDEOS, osakaDemoResult } from "./osakaDemo";

export const STAGE = { pick: 3, firstResult: 30, final: 150 } as const;
const SEGMENTS = 6;

function randomToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

const shortName = (name: string) => name.split(" · ")[0];

function qualityAt(videoIndex: number, t: number): VideoQuality {
  return t >= DEMO_VIDEOS[videoIndex].fullAt ? "FULL" : "PREVIEW";
}

function videosAt(full: JobResult, t: number): VideoProgress[] {
  if (t < STAGE.pick) return [];
  return DEMO_VIDEOS.map((v, i) => {
    const names = full.places
      .filter((p) => p.evidence.some((e) => e.videoId === v.videoId))
      .map((p) => shortName(p.name));
    // 영상마다 속도를 조금씩 다르게
    const span = (STAGE.firstResult - STAGE.pick) * (0.7 + 0.075 * i);
    const ratio = Math.min(1, Math.max(0, (t - STAGE.pick) / span));
    const done = t >= STAGE.firstResult ? SEGMENTS : Math.floor(ratio * SEGMENTS);
    const finished = t >= STAGE.firstResult;
    return {
      videoId: v.videoId,
      title: v.title,
      channelTitle: v.channelTitle,
      state: finished ? "DONE" : "ANALYZING",
      segments: { total: SEGMENTS, done },
      previewNames: names.slice(0, Math.ceil((done / SEGMENTS) * names.length)),
      quality: finished ? qualityAt(i, t) : undefined,
    };
  });
}

/** 진행 중 결과: 근거 영상이 모두 FULL이 된 장소만 평가를 보여 준다. */
function resultAt(full: JobResult, t: number): JobResult {
  const fullVideos = new Set(DEMO_VIDEOS.filter((_, i) => qualityAt(i, t) === "FULL").map((v) => v.videoId));
  const places: ResultPlace[] = full.places.map((p) => {
    const pending = p.evidence.some((e) => !fullVideos.has(e.videoId));
    return pending
      ? { ...p, ratings: {}, timeEvidence: [], pendingEnrichment: true, revision: 0 }
      : { ...p, pendingEnrichment: false, revision: 1 };
  });
  return { ...full, places };
}

/** 단계적 가짜 API. now·secondMs는 테스트에서 바꾼다. */
export function createMockApi({ secondMs = 250, now = () => Date.now() } = {}): Api {
  const jobs = new Map<string, number>();

  return {
    mode: "mock",
    async createJob() {
      const jobId = crypto.randomUUID();
      jobs.set(jobId, now());
      return { jobId, guestAccessToken: randomToken(), status: "QUEUED" };
    },
    async getJob(jobId): Promise<GetJobResponse> {
      // 새로고침으로 메모리가 비면 끝난 작업으로 본다
      const createdAt = jobs.get(jobId) ?? -Infinity;
      const t = secondMs > 0 ? (now() - createdAt) / secondMs : Infinity;
      const full = osakaDemoResult(jobId);
      const videos = videosAt(full, t);
      const final = t >= STAGE.final;
      const live = t >= STAGE.firstResult;
      return {
        jobId,
        status: final ? "SUCCEEDED" : t < STAGE.pick ? "QUEUED" : "RUNNING",
        progress: {
          total: videos.length,
          analyzed: videos.filter((v) => v.state === "DONE").length,
          failed: 0,
        },
        videos,
        result: final ? resultAt(full, Infinity) : live ? resultAt(full, t) : null,
        resultStage: final ? "FINAL" : live ? "PARTIAL_LIVE" : undefined,
      };
    },
  };
}

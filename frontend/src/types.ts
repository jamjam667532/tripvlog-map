// backend/shared/schemas/api.py, result.py와 같은 형식 (spec §3, §6.4)

export const STYLES = ["맛집", "카페·포토스팟", "관광·역사", "쇼핑", "가성비"] as const;
export type Style = (typeof STYLES)[number];

export const COMPANIONS = ["혼자", "커플", "친구", "가족"] as const;
export type Companion = (typeof COMPANIONS)[number];

export const MAX_STYLES = 3;

export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED";
export type VideoState = "PENDING" | "ANALYZING" | "DONE" | "FAILED" | "SKIPPED";

export const TERMINAL_STATUSES: readonly JobStatus[] = ["SUCCEEDED", "PARTIAL", "FAILED"];

export type Category = "RESTAURANT" | "CAFE" | "ATTRACTION" | "OTHER";
export type MatchStatus = "CONFIRMED" | "UNCONFIRMED";
export type RatingAspect = "taste" | "price" | "wait" | "service";
export type TimeEvidenceKind = "SCENE" | "STATED_TIME" | "WAIT_EXPERIENCE" | "CREATOR_TIP";
export type Situation =
  | "OPENING"
  | "MORNING"
  | "LUNCH_PEAK"
  | "AFTERNOON"
  | "EVENING"
  | "NIGHT"
  | "SUNSET"
  | "DAY"
  | "OTHER";

export interface CreateJobRequest {
  requestId: string;
  destination: string;
  styles: Style[];
  companion: Companion | null;
}

export interface CreateJobResponse {
  jobId: string;
  guestAccessToken: string;
  status: JobStatus;
}

export interface Progress {
  total: number;
  analyzed: number;
  failed: number;
}

export interface VideoProgress {
  videoId: string;
  state: VideoState;
}

export interface RatingCount {
  positive: number;
  negative: number;
  mixed: number;
}

export interface TimeEvidenceSummary {
  kind: TimeEvidenceKind;
  situation: Situation;
  channels: number;
  recommend: boolean;
}

export interface EvidenceLink {
  channelId: string;
  videoId: string;
  startSec: number; // 영상 재생 위치. 방문 시각이 아니다
  text: string;
}

export interface ResultPlace {
  placeId: string;
  name: string; // 영상 기반 표기 (결정 0002-4)
  category: Category;
  lat: number;
  lng: number;
  areaGroup: string | null;
  rank: number;
  matchStatus: MatchStatus;
  channels: { visited: number; denominator: number };
  ratings: Partial<Record<RatingAspect, RatingCount>>;
  timeEvidence: TimeEvidenceSummary[];
  evidence: EvidenceLink[];
}

export interface UnconfirmedPlace {
  names: string[];
  reason: "MULTIPLE_BRANCHES";
}

export interface JobResult {
  jobId: string;
  destination: string;
  analyzedChannels: number;
  failedVideos: number;
  places: ResultPlace[];
  unconfirmed: UnconfirmedPlace[];
}

export interface GetJobResponse {
  jobId: string;
  status: JobStatus;
  progress: Progress;
  videos: VideoProgress[];
  result: JobResult | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string };
  jobId?: string;
}

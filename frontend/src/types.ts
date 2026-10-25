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

// 아래 선택 필드는 단계적 결과 화면용 제안(docs/memo-frontend-progressive-ui-reply.md).
// 백엔드가 아직 보내지 않으므로 모두 선택이다.
export type VideoQuality = "PREVIEW" | "FULL";
export type ResultStage = "PARTIAL_LIVE" | "FINAL";

export interface VideoProgress {
  videoId: string;
  state: VideoState;
  title?: string;
  channelTitle?: string;
  segments?: { total: number; done: number };
  previewNames?: string[]; // 확인 전 이름(Gemini 원문). 지도·장소 카드에 쓰지 않는다
  quality?: VideoQuality;
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
  pendingEnrichment?: boolean; // 평가 보강 중(미리보기 근거만 있음)
  revision?: number; // 근거·평가가 바뀔 때마다 증가
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
  resultStage?: ResultStage;
}

export interface ApiErrorBody {
  error: { code: string; message: string };
  jobId?: string;
}

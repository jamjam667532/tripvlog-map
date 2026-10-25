// 화면 표현 규칙 (spec §6.3). 순수 함수만 둔다.
import type {
  Category,
  RatingAspect,
  RatingCount,
  Situation,
  TimeEvidenceKind,
  TimeEvidenceSummary,
  VideoState,
} from "./types";

export const CATEGORY_LABEL: Record<Category, string> = {
  RESTAURANT: "식당",
  CAFE: "카페",
  ATTRACTION: "관광지",
  OTHER: "기타",
};

export const ASPECT_LABEL: Record<RatingAspect, string> = {
  taste: "맛",
  price: "가격",
  wait: "대기",
  service: "서비스",
};

export const KIND_LABEL: Record<TimeEvidenceKind, string> = {
  SCENE: "장면",
  STATED_TIME: "방문 시각 언급",
  WAIT_EXPERIENCE: "대기 경험",
  CREATOR_TIP: "제작자 추천",
};

export const SITUATION_LABEL: Record<Situation, string> = {
  OPENING: "오픈 직후",
  MORNING: "오전",
  LUNCH_PEAK: "점심 피크",
  AFTERNOON: "오후",
  EVENING: "저녁",
  NIGHT: "밤",
  SUNSET: "해 질 무렵",
  DAY: "낮",
  OTHER: "기타 시간",
};

export const VIDEO_STATE_LABEL: Record<VideoState, string> = {
  PENDING: "대기",
  ANALYZING: "분석 중",
  DONE: "완료",
  FAILED: "실패",
  SKIPPED: "건너뜀",
};

/** 재생 위치를 "영상 12:30 지점"으로. 방문 시각처럼 보이지 않게 항상 "영상 … 지점"을 붙인다. */
export function formatVideoPosition(startSec: number): string {
  const s = Math.max(0, Math.floor(startSec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  const clock = h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
  return `영상 ${clock} 지점`;
}

export function youtubeLink(videoId: string, startSec: number): string {
  return `https://youtu.be/${encodeURIComponent(videoId)}?t=${Math.max(0, Math.floor(startSec))}`;
}

/** 표본 수를 항상 함께: "분석 성공 5개 채널 중 4개 방문" */
export function formatChannelSample(visited: number, denominator: number): string {
  return `분석 성공 ${denominator}개 채널 중 ${visited}개 방문`;
}

/** "추천"은 aggregate가 recommend를 준 경우만. 그 외는 "영상 속 경험" / "영상 속 … 장면". */
export function formatTimeEvidence(t: TimeEvidenceSummary): string {
  const situation = SITUATION_LABEL[t.situation];
  const count = `채널 ${t.channels}곳`;
  if (t.recommend) return `${situation} 추천 · ${count}`;
  if (t.kind === "SCENE") return `영상 속 ${situation} 방문 장면 · ${count}`;
  return `영상 속 경험: ${situation} · ${count}`;
}

/** "맛 긍정 2 · 혼합 1". 집계가 0뿐이면 null. */
export function formatRating(aspect: RatingAspect, r: RatingCount): string | null {
  const parts: string[] = [];
  if (r.positive) parts.push(`긍정 ${r.positive}`);
  if (r.negative) parts.push(`부정 ${r.negative}`);
  if (r.mixed) parts.push(`혼합 ${r.mixed}`);
  return parts.length ? `${ASPECT_LABEL[aspect]} ${parts.join(" · ")}` : null;
}

// 진행 중 결과를 여러 번 받을 때 "보던 화면"을 지키는 규칙. 순수 함수만 둔다.
//
// - 카드 순서는 사용자가 정렬을 누르거나 결과가 FINAL이 될 때만 순위대로 바꾼다.
// - 새로 나온 장소는 기존 순서 뒤에 (순위 순으로) 붙인다.
// - revision이 오른 장소는 강조하고, 그중 평가·시간 근거가 실제로 있는 장소만 "새 평가"로 센다.
//   처음 받은 결과는 세지 않는다.
import type { ResultPlace, ResultStage } from "./types";

export interface LiveState {
  places: ResultPlace[]; // 마지막으로 반영한 응답(참조 비교용)
  stage: ResultStage | undefined; // 장소가 그대로여도 단계가 바뀌면 다시 반영한다
  order: string[]; // 화면 카드 순서 (placeId)
  revisions: Record<string, number>;
  fresh: string[]; // 강조할 장소: 새로 나왔거나 평가가 붙음
  newRatings: number; // "새 평가 N개"
  finalSorted: boolean;
}

const hasRating = (places: ResultPlace[], id: string) => {
  const p = places.find((x) => x.placeId === id);
  return !!p && (Object.keys(p.ratings).length > 0 || p.timeEvidence.length > 0);
};

export const needsAdvance = (s: LiveState, places: ResultPlace[], stage: ResultStage | undefined) =>
  s.places !== places || s.stage !== stage;

export const rankOrder = (places: ResultPlace[]): string[] =>
  [...places].sort((a, b) => a.rank - b.rank).map((p) => p.placeId);

export function initLive(places: ResultPlace[], stage: ResultStage | undefined): LiveState {
  return {
    places,
    stage,
    order: rankOrder(places),
    revisions: Object.fromEntries(places.map((p) => [p.placeId, p.revision ?? 0])),
    fresh: [],
    newRatings: 0,
    finalSorted: stage !== "PARTIAL_LIVE",
  };
}

export function advanceLive(prev: LiveState, places: ResultPlace[], stage: ResultStage | undefined): LiveState {
  const known = new Set(prev.order);
  const added = rankOrder(places.filter((p) => !known.has(p.placeId)));
  const present = new Set(places.map((p) => p.placeId));
  const updated = places
    .filter((p) => known.has(p.placeId) && (p.revision ?? 0) > (prev.revisions[p.placeId] ?? 0))
    .map((p) => p.placeId);

  const sortNow = stage !== "PARTIAL_LIVE" && !prev.finalSorted;
  const order = sortNow
    ? rankOrder(places)
    : [...prev.order.filter((id) => present.has(id)), ...added];

  return {
    places,
    stage,
    order,
    revisions: Object.fromEntries(places.map((p) => [p.placeId, p.revision ?? 0])),
    fresh: [...new Set([...prev.fresh.filter((id) => present.has(id)), ...added, ...updated])],
    newRatings: prev.newRatings + updated.filter((id) => hasRating(places, id)).length,
    finalSorted: prev.finalSorted || sortNow,
  };
}

export const acknowledge = (s: LiveState): LiveState => ({ ...s, fresh: [], newRatings: 0 });

export const sortByRank = (s: LiveState): LiveState => ({ ...s, order: rankOrder(s.places) });

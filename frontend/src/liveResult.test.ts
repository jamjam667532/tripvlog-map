import { describe, expect, it } from "vitest";

import { acknowledge, advanceLive, initLive, needsAdvance, sortByRank } from "./liveResult";
import type { ResultPlace } from "./types";

const place = (placeId: string, rank: number, revision = 0): ResultPlace => ({
  placeId,
  name: placeId,
  category: "RESTAURANT",
  lat: 0,
  lng: 0,
  areaGroup: null,
  rank,
  matchStatus: "CONFIRMED",
  channels: { visited: 1, denominator: 5 },
  ratings: {},
  timeEvidence: [],
  evidence: [],
  revision,
});

describe("liveResult", () => {
  it("진행 중에는 순위가 바뀌어도 보던 순서를 지키고 새 장소는 뒤에 붙인다", () => {
    let s = initLive([place("a", 1), place("b", 2)], "PARTIAL_LIVE");
    s = advanceLive(s, [place("b", 1), place("a", 2), place("d", 4), place("c", 3)], "PARTIAL_LIVE");
    expect(s.order).toEqual(["a", "b", "c", "d"]);
    expect(s.fresh).toEqual(["c", "d"]);
    expect(s.newRatings).toBe(0);
  });

  it("revision이 오른 장소를 강조하고, 평가가 실제로 붙은 것만 새 평가로 센다", () => {
    const rated = (p: ResultPlace): ResultPlace => ({ ...p, ratings: { taste: { positive: 1, negative: 0, mixed: 0 } } });
    let s = initLive([place("a", 1, 0), place("b", 2, 0)], "PARTIAL_LIVE");
    s = advanceLive(s, [rated(place("a", 1, 1)), place("b", 2, 0)], "PARTIAL_LIVE");
    expect(s.newRatings).toBe(1);
    expect(s.fresh).toEqual(["a"]);
    // b는 보강이 끝났지만 평가가 없다 → 강조만, 개수에는 안 넣는다
    s = advanceLive(s, [rated(place("a", 1, 1)), place("b", 2, 1)], "PARTIAL_LIVE");
    expect(s.newRatings).toBe(1);
    expect(s.fresh).toEqual(["a", "b"]);
    expect(acknowledge(s)).toMatchObject({ newRatings: 0, fresh: [] });
  });

  it("FINAL이 되면 한 번만 순위대로 정렬한다", () => {
    let s = initLive([place("a", 1), place("b", 2)], "PARTIAL_LIVE");
    s = advanceLive(s, [place("a", 2), place("b", 1)], "FINAL");
    expect(s.order).toEqual(["b", "a"]);
    // 이후 응답에서는 다시 정렬하지 않는다
    s = advanceLive(s, [place("a", 1), place("b", 2)], "FINAL");
    expect(s.order).toEqual(["b", "a"]);
  });

  it("장소는 그대로이고 단계만 FINAL로 바뀌어도 정렬한다", () => {
    const places = [place("a", 2), place("b", 1)];
    const s = initLive(places, "PARTIAL_LIVE");
    expect(s.order).toEqual(["b", "a"]);
    const moved = { ...s, order: ["a", "b"] };
    expect(needsAdvance(moved, places, "FINAL")).toBe(true);
    expect(advanceLive(moved, places, "FINAL").order).toEqual(["b", "a"]);
  });

  it("사용자가 정렬을 누르면 순위대로", () => {
    let s = initLive([place("a", 1), place("b", 2)], "PARTIAL_LIVE");
    s = advanceLive(s, [place("a", 2), place("b", 1)], "PARTIAL_LIVE");
    expect(sortByRank(s).order).toEqual(["b", "a"]);
  });

  it("처음 받은 결과가 FINAL이면 정렬된 상태로 시작한다", () => {
    const s = initLive([place("a", 2), place("b", 1)], undefined);
    expect(s.order).toEqual(["b", "a"]);
    expect(s.finalSorted).toBe(true);
  });
});

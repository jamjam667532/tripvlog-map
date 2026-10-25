import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { osakaDemoResult } from "../mock/osakaDemo";
import type { JobResult } from "../types";
import ResultView from "./ResultView";

vi.mock("./MapPanel", () => ({ default: () => <div data-testid="map" /> }));

const ALL_NAMES = osakaDemoResult("j").places.map((p) => p.name);
// 카드 버튼 순서대로 장소 이름만 (순위 숫자·배지는 바뀔 수 있다)
const names = () =>
  screen
    .getAllByRole("button", { name: /^\d+/ })
    .map((b) => ALL_NAMES.find((n) => (b.textContent ?? "").includes(n)) ?? "?");

function live(base: JobResult, keep: number): JobResult {
  // 앞쪽 장소 일부만, 평가 보강 중으로
  return {
    ...base,
    places: base.places.slice(0, keep).map((p) => ({ ...p, ratings: {}, pendingEnrichment: true, revision: 0 })),
  };
}

describe("ResultView 진행 중 결과", () => {
  it("새 결과가 와도 보던 순서를 지키고, 평가가 붙으면 '새 평가 N개'를 띄운다", () => {
    const full = osakaDemoResult("j");
    const first = live(full, 3);
    const { rerender } = render(<ResultView result={first} stage="PARTIAL_LIVE" videos={[]} demo={false} onReset={() => {}} />);
    expect(screen.getAllByText("평가 보강 중")).toHaveLength(3);
    expect(screen.getAllByText(/지금까지 분석한 5개 채널 중/).length).toBe(3);

    // 순위가 뒤집힌 응답 + 새 장소 + 첫 장소 평가 반영
    const second: JobResult = {
      ...full,
      places: [
        { ...full.places[1], rank: 3, pendingEnrichment: false, revision: 1 },
        { ...first.places[0], rank: 1 },
        { ...first.places[2], rank: 2 },
        { ...full.places[3], pendingEnrichment: true, revision: 0 },
      ],
    };
    const before = names();
    rerender(<ResultView result={second} stage="PARTIAL_LIVE" videos={[]} demo={false} onReset={() => {}} />);
    expect(names().slice(0, 3)).toEqual(before);
    expect(names()).toHaveLength(4);
    expect(screen.getByRole("button", { name: /새 평가 1개/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /새 평가 1개/ }));
    expect(screen.queryByRole("button", { name: /새 평가/ })).toBeNull();

    // FINAL이면 순위대로
    rerender(<ResultView result={{ ...second }} stage="FINAL" videos={[]} demo={false} onReset={() => {}} />);
    expect(names()[0]).toBe(first.places[0].name);
    expect(screen.getByText("완료")).toBeInTheDocument();
  });

  it("분류 탭으로 카페만 본다", () => {
    render(<ResultView result={osakaDemoResult("j")} stage={undefined} videos={[]} demo={false} onReset={() => {}} />);
    fireEvent.click(screen.getByRole("tab", { name: "카페" }));
    expect(names().every((n) => /커피|아일랜드/.test(n))).toBe(true);
  });
});

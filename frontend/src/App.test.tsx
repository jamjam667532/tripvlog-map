import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";
import { createMockApi } from "./mock/mockApi";

// jsdom에서는 Google 지도를 띄우지 않는다
vi.mock("./components/MapPanel", () => ({ default: () => <div data-testid="map" /> }));

function renderApp(secondMs: number) {
  sessionStorage.clear();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App api={createMockApi({ secondMs })} />
    </QueryClientProvider>,
  );
}

describe("App", () => {
  it("목적지를 입력해야 분석을 시작할 수 있다", () => {
    renderApp(1);
    const submit = screen.getByRole("button", { name: "분석 시작" });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("어디로 가시나요?"), { target: { value: "오사카" } });
    expect(submit).toBeEnabled();
  });

  it("스타일은 최대 3개까지 고를 수 있다", () => {
    renderApp(1);
    for (const s of ["맛집", "카페·포토스팟", "관광·역사", "쇼핑"]) {
      fireEvent.click(screen.getByRole("button", { name: s }));
    }
    expect(screen.getByRole("button", { name: "쇼핑" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "맛집" })).toHaveAttribute("aria-pressed", "true");
  });

  it("작업이 끝나면 표본 수·근거와 함께 결과를 보여준다", async () => {
    renderApp(0);
    fireEvent.change(screen.getByLabelText("어디로 가시나요?"), { target: { value: "오사카" } });
    fireEvent.click(screen.getByRole("button", { name: "분석 시작" }));

    expect(await screen.findByText("분석 성공 5개 채널 중 4개 방문")).toBeInTheDocument();
    expect(screen.getByText("오픈 직후 추천 · 채널 1곳")).toBeInTheDocument();
    expect(screen.getAllByText("시간 정보 없음").length).toBeGreaterThan(0);

    // 카드를 누르면 영상 근거 링크가 재생 위치로 열린다
    fireEvent.click(screen.getByRole("button", { name: /겟토타니마치/ }));
    const link = screen.getByRole("link", { name: /영상 14:18 지점/ });
    expect(link).toHaveAttribute("href", "https://youtu.be/vghwtv344yI?t=858");

    // 지역 필터
    fireEvent.click(screen.getByRole("button", { name: "기타하마" }));
    expect(screen.queryByText("글리코 사인 · 도톤보리")).toBeNull();
    expect(screen.getByText("모토커피 · 기타하마")).toBeInTheDocument();
  });
});

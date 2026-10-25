import { describe, expect, it } from "vitest";

import { formatChannelSample, formatRating, formatTimeEvidence, formatVideoPosition, youtubeLink } from "./format";

describe("formatVideoPosition", () => {
  it("재생 위치를 '영상 … 지점'으로 표기한다", () => {
    expect(formatVideoPosition(750)).toBe("영상 12:30 지점");
    expect(formatVideoPosition(5)).toBe("영상 0:05 지점");
    expect(formatVideoPosition(3725)).toBe("영상 1:02:05 지점");
  });
});

describe("youtubeLink", () => {
  it("재생 위치(초)로 링크한다", () => {
    expect(youtubeLink("abc_DEF-123", 750.9)).toBe("https://youtu.be/abc_DEF-123?t=750");
  });
});

describe("formatChannelSample", () => {
  it("표본 수를 항상 함께 보여준다", () => {
    expect(formatChannelSample(4, 5)).toBe("분석 성공 5개 채널 중 4개 방문");
    expect(formatChannelSample(2, 3, true)).toBe("지금까지 분석한 3개 채널 중 2개 방문");
  });
});

describe("formatTimeEvidence", () => {
  it("recommend가 있을 때만 '추천'", () => {
    expect(formatTimeEvidence({ kind: "CREATOR_TIP", situation: "OPENING", channels: 1, recommend: true })).toBe(
      "오픈 직후 추천 · 채널 1곳",
    );
  });

  it("recommend가 없으면 '영상 속 경험'", () => {
    const text = formatTimeEvidence({ kind: "WAIT_EXPERIENCE", situation: "LUNCH_PEAK", channels: 2, recommend: false });
    expect(text).toBe("영상 속 경험: 점심 피크 · 채널 2곳");
    expect(text).not.toContain("추천");
  });

  it("장면 관찰은 방문 장면으로만 표현한다", () => {
    expect(formatTimeEvidence({ kind: "SCENE", situation: "NIGHT", channels: 1, recommend: false })).toBe(
      "영상 속 밤 방문 장면 · 채널 1곳",
    );
  });
});

describe("formatRating", () => {
  it("0이 아닌 값만 나열한다", () => {
    expect(formatRating("taste", { positive: 3, negative: 0, mixed: 1 })).toBe("맛 긍정 3 · 혼합 1");
    expect(formatRating("wait", { positive: 0, negative: 0, mixed: 0 })).toBeNull();
  });
});

// 비로그인 jobId·guestAccessToken은 sessionStorage에 (spec §6.2). 저장소가 막혀도 동작해야 한다.

export interface GuestJob {
  jobId: string;
  guestAccessToken: string;
}

const KEY = "tripvlog.guestJob";

export function loadGuestJob(): GuestJob | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as GuestJob).jobId === "string" &&
      typeof (parsed as GuestJob).guestAccessToken === "string"
    ) {
      return parsed as GuestJob;
    }
  } catch {
    // 저장소 접근 불가·형식 오류는 무시한다
  }
  return null;
}

export function saveGuestJob(job: GuestJob): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(job));
  } catch {
    // 무시
  }
}

export function clearGuestJob(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // 무시
  }
}

import { useState } from "react";

import { COMPANIONS, MAX_STYLES, STYLES, type Companion, type CreateJobRequest, type Style } from "../types";

interface Props {
  onSubmit: (req: Omit<CreateJobRequest, "requestId">) => void;
  submitting: boolean;
  error: string | null;
}

const chip = (on: boolean) =>
  `rounded-full border px-4 py-2 text-sm transition ${
    on
      ? "border-[#14213D] bg-[#14213D] text-white"
      : "border-stone-300 bg-white text-stone-700 hover:border-stone-500"
  }`;

export default function JobForm({ onSubmit, submitting, error }: Props) {
  const [destination, setDestination] = useState("");
  const [styles, setStyles] = useState<Style[]>([]);
  const [companion, setCompanion] = useState<Companion | null>(null);

  const toggleStyle = (s: Style) =>
    setStyles((cur) =>
      cur.includes(s) ? cur.filter((x) => x !== s) : cur.length < MAX_STYLES ? [...cur, s] : cur,
    );

  const trimmed = destination.trim();

  return (
    <form
      className="mx-auto flex w-full max-w-xl flex-col gap-8 rounded-2xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8"
      onSubmit={(e) => {
        e.preventDefault();
        if (trimmed) onSubmit({ destination: trimmed, styles, companion });
      }}
    >
      <div className="flex flex-col gap-2">
        <label htmlFor="destination" className="text-sm font-semibold text-stone-700">
          어디로 가시나요?
        </label>
        <input
          id="destination"
          value={destination}
          maxLength={50}
          onChange={(e) => setDestination(e.target.value)}
          placeholder="예: 오사카"
          className="rounded-xl border border-stone-300 px-4 py-3 text-lg outline-none focus:border-[#E2703A] focus:ring-2 focus:ring-[#E2703A]/30"
        />
        <p className="text-xs text-stone-500">해외 도시 한 곳 · 서로 다른 채널의 한국어 브이로그 최대 5개를 분석합니다</p>
      </div>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-3 text-sm font-semibold text-stone-700">
          선호 스타일 <span className="font-normal text-stone-500">(선택, 최대 {MAX_STYLES}개)</span>
        </legend>
        <div className="flex flex-wrap gap-2">
          {STYLES.map((s) => (
            <button key={s} type="button" aria-pressed={styles.includes(s)} className={chip(styles.includes(s))} onClick={() => toggleStyle(s)}>
              {s}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-3 text-sm font-semibold text-stone-700">
          동행 <span className="font-normal text-stone-500">(선택)</span>
        </legend>
        <div className="flex flex-wrap gap-2">
          {COMPANIONS.map((c) => (
            <button
              key={c}
              type="button"
              aria-pressed={companion === c}
              className={chip(companion === c)}
              onClick={() => setCompanion((cur) => (cur === c ? null : c))}
            >
              {c}
            </button>
          ))}
        </div>
      </fieldset>

      {error && <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}

      <button
        type="submit"
        disabled={!trimmed || submitting}
        className="rounded-xl bg-[#E2703A] px-6 py-3 text-lg font-bold text-white transition hover:bg-[#c95f2d] disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "접수 중…" : "분석 시작"}
      </button>
    </form>
  );
}

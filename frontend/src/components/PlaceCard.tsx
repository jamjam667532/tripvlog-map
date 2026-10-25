import { forwardRef } from "react";

import {
  CATEGORY_LABEL,
  formatChannelSample,
  formatRating,
  formatTimeEvidence,
  formatVideoPosition,
  KIND_LABEL,
  youtubeLink,
} from "../format";
import type { RatingAspect, ResultPlace } from "../types";

interface Props {
  place: ResultPlace;
  selected: boolean;
  channelLabel: (channelId: string) => string;
  onSelect: () => void;
}

const ASPECTS: RatingAspect[] = ["taste", "price", "wait", "service"];

const PlaceCard = forwardRef<HTMLLIElement, Props>(function PlaceCard({ place, selected, channelLabel, onSelect }, ref) {
  const ratings = ASPECTS.map((a) => (place.ratings[a] ? formatRating(a, place.ratings[a]) : null)).filter(
    (x): x is string => x !== null,
  );

  return (
    <li
      ref={ref}
      className={`rounded-xl border bg-white p-4 transition ${
        selected ? "border-[#E2703A] ring-2 ring-[#E2703A]/30" : "border-stone-200 hover:border-stone-400"
      }`}
    >
      <button type="button" onClick={onSelect} className="flex w-full items-start gap-3 text-left">
        <span
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white ${
            selected ? "bg-[#E2703A]" : "bg-[#14213D]"
          }`}
        >
          {place.rank}
        </span>
        <span className="flex min-w-0 flex-col gap-1">
          <span className="font-bold text-[#14213D]">{place.name}</span>
          <span className="text-xs text-stone-500">
            {CATEGORY_LABEL[place.category]}
            {place.areaGroup ? ` · ${place.areaGroup}` : ""}
          </span>
          <span className="text-sm font-semibold text-[#B04A17]">
            {formatChannelSample(place.channels.visited, place.channels.denominator)}
          </span>
        </span>
      </button>

      <div className="mt-3 flex flex-col gap-2 pl-11 text-sm">
        <p className="text-stone-700">{ratings.length ? ratings.join(" · ") : "평가 없음"}</p>

        {place.timeEvidence.length ? (
          <ul className="flex flex-col gap-1">
            {place.timeEvidence.map((t, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-semibold ${
                    t.recommend ? "bg-[#FBE3D3] text-[#9a3f12]" : "bg-stone-100 text-stone-600"
                  }`}
                >
                  {KIND_LABEL[t.kind]}
                </span>
                <span className="text-stone-700">{formatTimeEvidence(t)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-stone-400">시간 정보 없음</p>
        )}

        {selected && (
          <ul className="mt-1 flex flex-col gap-2 border-t border-stone-100 pt-3">
            {place.evidence.map((e) => (
              <li key={`${e.videoId}-${e.startSec}`} className="flex flex-col gap-0.5">
                <a
                  href={youtubeLink(e.videoId, e.startSec)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs font-semibold text-[#2D5BA8] hover:underline"
                >
                  {channelLabel(e.channelId)} · {formatVideoPosition(e.startSec)} ▶
                </a>
                <q className="text-stone-600">{e.text}</q>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
});

export default PlaceCard;

import { AdvancedMarker, APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import { useEffect, useRef, useState } from "react";

import type { ResultPlace } from "../types";

interface Props {
  places: ResultPlace[];
  selectedId: string | null;
  freshIds: ReadonlySet<string>;
  // 이 값이 바뀔 때만 지도 범위를 다시 맞춘다(필터 변경). 진행 중 핀이 늘어날 때는 사용자가 움직인 대로 둔다.
  fitKey: string;
  onSelect: (placeId: string) => void;
}

const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined;
// Advanced Marker에 필요한 지도 ID. 콘솔에서 만든 ID가 있으면 VITE_GOOGLE_MAPS_MAP_ID로 바꾼다.
const MAP_ID = (import.meta.env.VITE_GOOGLE_MAPS_MAP_ID as string | undefined) || "DEMO_MAP_ID";

function FitAndFocus({ places, selectedId, fitKey }: Pick<Props, "places" | "selectedId" | "fitKey">) {
  const map = useMap();
  const fittedFor = useRef<string | null>(null);
  const coords = JSON.stringify(places.map((p) => [p.lat, p.lng]));

  useEffect(() => {
    const points = JSON.parse(coords) as [number, number][];
    if (!map || points.length === 0 || fittedFor.current === fitKey) return;
    fittedFor.current = fitKey;
    const bounds = new google.maps.LatLngBounds();
    points.forEach(([lat, lng]) => bounds.extend({ lat, lng }));
    map.fitBounds(bounds, 48);
  }, [map, coords, fitKey]);

  useEffect(() => {
    if (!map || !selectedId) return;
    const p = places.find((x) => x.placeId === selectedId);
    if (p) map.panTo({ lat: p.lat, lng: p.lng });
  }, [map, places, selectedId]);

  return null;
}

export default function MapPanel({ places, selectedId, freshIds, fitKey, onSelect }: Props) {
  // 렌더마다 새 객체를 넘기면 카메라가 초기값으로 돌아가므로 처음 한 번만 만든다
  const [center, setCenter] = useState(() => (places[0] ? { lat: places[0].lat, lng: places[0].lng } : null));
  if (!center && places[0]) setCenter({ lat: places[0].lat, lng: places[0].lng });

  if (!API_KEY) {
    return (
      <div className="flex h-full items-center justify-center bg-stone-100 p-6 text-center text-sm text-stone-500">
        지도 키가 없습니다. frontend/.env.local에 VITE_GOOGLE_MAPS_API_KEY를 넣으면 Google 지도가 표시됩니다.
      </div>
    );
  }

  // 장소가 없으면 엉뚱한 도시를 띄우지 않는다
  if (!center) {
    return (
      <div className="flex h-full items-center justify-center bg-stone-100 p-6 text-center text-sm text-stone-500">
        지도에 표시할 확정 장소가 아직 없습니다
      </div>
    );
  }

  return (
    <APIProvider apiKey={API_KEY} language="ko" region="KR">
      <Map mapId={MAP_ID} defaultCenter={center} defaultZoom={13} gestureHandling="greedy" className="h-full w-full">
        {places.map((p) => {
          const on = p.placeId === selectedId;
          const fresh = freshIds.has(p.placeId);
          return (
            <AdvancedMarker
              key={p.placeId}
              position={{ lat: p.lat, lng: p.lng }}
              title={`${p.rank}. ${p.name}`}
              zIndex={on ? 1000 : fresh ? 500 : 100 - p.rank}
              onClick={() => onSelect(p.placeId)}
            >
              {/* Pin 컴포넌트는 만든 뒤 색·크기 변경이 반영되지 않아 직접 그린다 */}
              <span
                className={`flex items-center justify-center rounded-full border-2 border-white font-bold text-white shadow-md transition-all duration-300 ${
                  on
                    ? "h-10 w-10 bg-[#E2703A] text-base"
                    : fresh
                      ? "h-9 w-9 bg-[#2D5BA8] text-sm ring-4 ring-[#2D5BA8]/30"
                      : "h-8 w-8 bg-[#14213D] text-sm"
                }`}
              >
                {p.rank}
              </span>
            </AdvancedMarker>
          );
        })}
        <FitAndFocus places={places} selectedId={selectedId} fitKey={fitKey} />
      </Map>
    </APIProvider>
  );
}

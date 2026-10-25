import { AdvancedMarker, APIProvider, Map, Pin, useMap } from "@vis.gl/react-google-maps";
import { useEffect, useState } from "react";

import type { ResultPlace } from "../types";

interface Props {
  places: ResultPlace[];
  selectedId: string | null;
  onSelect: (placeId: string) => void;
}

const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY as string | undefined;
// Advanced Marker에 필요한 지도 ID. 콘솔에서 만든 ID가 있으면 VITE_GOOGLE_MAPS_MAP_ID로 바꾼다.
const MAP_ID = (import.meta.env.VITE_GOOGLE_MAPS_MAP_ID as string | undefined) || "DEMO_MAP_ID";

function FitAndFocus({ places, selectedId }: Pick<Props, "places" | "selectedId">) {
  const map = useMap();
  // 배열 참조가 바뀌어도 좌표가 같으면 다시 맞추지 않는다(선택 확대가 풀리지 않게)
  const coords = JSON.stringify(places.map((p) => [p.lat, p.lng]));

  useEffect(() => {
    const points = JSON.parse(coords) as [number, number][];
    if (!map || points.length === 0) return;
    const bounds = new google.maps.LatLngBounds();
    points.forEach(([lat, lng]) => bounds.extend({ lat, lng }));
    map.fitBounds(bounds, 48);
  }, [map, coords]);

  useEffect(() => {
    if (!map || !selectedId) return;
    const p = places.find((x) => x.placeId === selectedId);
    if (!p) return;
    map.panTo({ lat: p.lat, lng: p.lng });
  }, [map, places, selectedId]);

  return null;
}

export default function MapPanel({ places, selectedId, onSelect }: Props) {
  // 렌더마다 새 객체를 넘기면 카메라가 초기값으로 돌아가므로 처음 한 번만 만든다
  const [initialCenter] = useState(() =>
    places[0] ? { lat: places[0].lat, lng: places[0].lng } : { lat: 34.6937, lng: 135.5023 },
  );

  if (!API_KEY) {
    return (
      <div className="flex h-full items-center justify-center bg-stone-100 p-6 text-center text-sm text-stone-500">
        지도 키가 없습니다. frontend/.env.local에 VITE_GOOGLE_MAPS_API_KEY를 넣으면 Google 지도가 표시됩니다.
      </div>
    );
  }

  return (
    <APIProvider apiKey={API_KEY} language="ko" region="KR">
      <Map
        mapId={MAP_ID}
        defaultCenter={initialCenter}
        defaultZoom={13}
        gestureHandling="greedy"
        className="h-full w-full"
      >
        {places.map((p) => {
          const on = p.placeId === selectedId;
          return (
            <AdvancedMarker
              key={p.placeId}
              position={{ lat: p.lat, lng: p.lng }}
              title={`${p.rank}. ${p.name}`}
              zIndex={on ? 1000 : 100 - p.rank}
              onClick={() => onSelect(p.placeId)}
            >
              <Pin
                background={on ? "#E2703A" : "#14213D"}
                borderColor={on ? "#9a3f12" : "#0b1222"}
                glyphColor="#ffffff"
                glyph={String(p.rank)}
                scale={on ? 1.3 : 1}
              />
            </AdvancedMarker>
          );
        })}
        <FitAndFocus places={places} selectedId={selectedId} />
      </Map>
    </APIProvider>
  );
}

import { useMemo, useState } from "react";

type Place = {
  id: number;
  name: string;
  category: string;
  area: string;
  visits: number;
  positive: number;
  negative: number;
  time: string;
  evidence: string;
  channel: string;
  videoTime: string;
  image: string;
  tags: string[];
};

const places: Place[] = [
  {
    id: 1, name: "이치란 라멘 도톤보리점", category: "맛집", area: "도톤보리",
    visits: 4, positive: 3, negative: 1, time: "점심 피크 대기 경험",
    evidence: "국물 진짜 맛있는데, 점심에 왔더니 40분 기다렸어요.",
    channel: "오늘의 여행", videoTime: "12:30",
    image: "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?auto=format&fit=crop&w=900&q=85",
    tags: ["라멘", "웨이팅", "현지 맛집"]
  },
  {
    id: 2, name: "글리코상 · 도톤보리 강변", category: "관광", area: "난바",
    visits: 5, positive: 3, negative: 0, time: "시간 정보 없음",
    evidence: "오사카 오면 여기는 꼭 찍어야죠. 밤에 보니까 더 예뻐요.",
    channel: "소소한 지구여행", videoTime: "08:14",
    image: "https://images.unsplash.com/photo-1590559899731-a382839e5549?auto=format&fit=crop&w=900&q=85",
    tags: ["랜드마크", "야경", "사진"]
  },
  {
    id: 3, name: "LiLo Coffee Roasters", category: "카페", area: "신사이바시",
    visits: 3, positive: 3, negative: 0, time: "시간 정보 없음",
    evidence: "원두 향이 확실하고 커피 취향에 맞게 추천해줘요.",
    channel: "주말의 기록", videoTime: "05:42",
    image: "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?auto=format&fit=crop&w=900&q=85",
    tags: ["스페셜티", "커피", "감성 카페"]
  },
  {
    id: 4, name: "구로몬 시장", category: "시장", area: "닛폰바시",
    visits: 3, positive: 2, negative: 1, time: "오픈 직후 추천 근거 없음",
    evidence: "먹거리가 다양해요. 다만 사람이 많아서 이동하기는 조금 불편했어요.",
    channel: "여행하는 하루", videoTime: "16:08",
    image: "https://images.unsplash.com/photo-1555394130-7b4d6e2f3a0f?auto=format&fit=crop&w=900&q=85",
    tags: ["길거리 음식", "쇼핑", "시장"]
  }
];

const styles = ["전체", "맛집", "카페", "관광", "쇼핑"];
const companions = ["혼자", "커플", "친구", "가족"];

function Icon({ children }: { children: React.ReactNode }) {
  return <span className="icon" aria-hidden="true">{children}</span>;
}

export default function App() {
  const [destination, setDestination] = useState("오사카");
  const [selectedStyles, setSelectedStyles] = useState<string[]>(["맛집", "카페"]);
  const [companion, setCompanion] = useState("커플");
  const [showResults, setShowResults] = useState(true);
  const [activeFilter, setActiveFilter] = useState("전체");
  const [selectedPlace, setSelectedPlace] = useState(places[0]);
  const [mobileTab, setMobileTab] = useState<"places" | "map">("places");
  const [saved, setSaved] = useState<number[]>([2]);
  const [notice, setNotice] = useState("");

  const filteredPlaces = useMemo(
    () => places.filter((place) => activeFilter === "전체" || place.category === activeFilter),
    [activeFilter]
  );

  function toggleStyle(style: string) {
    setSelectedStyles((current) =>
      current.includes(style) ? current.filter((item) => item !== style) : [...current, style]
    );
  }

  function startAnalysis() {
    if (!destination.trim()) {
      setNotice("여행할 도시를 입력해 주세요.");
      return;
    }
    setNotice(`${destination.trim()} 브이로그 분석 미리보기를 열었어요.`);
    setShowResults(true);
  }

  function toggleSaved(id: number) {
    setSaved((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" onClick={(e) => { e.preventDefault(); setShowResults(false); }}>
          <span className="brand-mark"><Icon>✳</Icon></span>
          <span className="brand-word">trip<span>vlog</span></span>
          <span className="brand-beta">BETA</span>
        </a>
        <nav className="desktop-nav" aria-label="주 메뉴">
          <button className={!showResults ? "nav-link active" : "nav-link"} onClick={() => setShowResults(false)}>여행지 탐색</button>
          <button className={showResults ? "nav-link active" : "nav-link"} onClick={() => setShowResults(true)}>지도 & 근거</button>
          <a className="nav-link muted" href="#how-it-works">서비스 소개</a>
        </nav>
        <div className="topbar-actions">
          <button className="icon-button" aria-label="알림" onClick={() => setNotice("새로운 알림이 없습니다.")}><Icon>♧</Icon></button>
          <button className="profile-button" onClick={() => setNotice("로그인 기능은 다음 단계에서 연결할 예정이에요.")}><span>G</span><span className="profile-label">게스트</span><span>⌄</span></button>
        </div>
      </header>

      {!showResults ? (
        <main className="discovery-page">
          <section className="hero">
            <div className="hero-copy">
              <div className="eyebrow"><span className="eyebrow-dot" /> YOUR NEXT CHAPTER STARTS HERE</div>
              <h1>좋아하는 여행 유튜버의<br /><em>발자취를 따라</em> 여행해요.</h1>
              <p className="hero-description">수많은 브이로그를 하나씩 볼 필요 없이.<br />영상 속 장소와 생생한 경험을 지도 한 장에 모아보세요.</p>
              <div className="hero-search">
                <Icon>⌕</Icon>
                <input value={destination} onChange={(e) => setDestination(e.target.value)} onKeyDown={(e) => e.key === "Enter" && startAnalysis()} placeholder="어디로 떠나고 싶나요? 예: 오사카" aria-label="여행 목적지" />
                <button onClick={startAnalysis}>여행지 분석하기 <span>↗</span></button>
              </div>
              <div className="search-caption"><Icon>✦</Icon> 한국어 여행 브이로그를 분석해 방문 근거를 모아요</div>
            </div>
            <div className="hero-visual">
              <div className="hero-photo hero-photo-main"><img src="https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?auto=format&fit=crop&w=1200&q=90" alt="일본 교토의 전통 거리" /></div>
              <div className="hero-photo hero-photo-small"><img src="https://images.unsplash.com/photo-1554797589-7241bb691973?auto=format&fit=crop&w=600&q=85" alt="일본 여행 거리" /></div>
              <div className="floating-note"><span className="note-icon">▶</span><div><b>여행의 순간을 모으다</b><small>From vlog to your map</small></div></div>
              <div className="photo-stamp">TRAVEL<br />SLOWLY <span>✳</span></div>
            </div>
          </section>

          <section className="preference-section">
            <div className="section-heading"><div><span className="section-kicker">MAKE IT YOURS</span><h2>어떤 여행을 좋아하세요?</h2><p>선택한 취향에 맞는 브이로그와 장소를 먼저 보여드릴게요.</p></div><span className="step-label">01 <i>/</i> 02</span></div>
            <div className="preference-grid">
              <div className="preference-card">
                <div className="pref-title"><span>01</span><b>관심 있는 여행 스타일</b><small>복수 선택 가능</small></div>
                <div className="style-options">
                  {["맛집", "카페", "관광·역사", "쇼핑", "가성비"].map((style, i) => (
                    <button key={style} className={`style-option ${selectedStyles.includes(style) ? "selected" : ""}`} onClick={() => toggleStyle(style)}>
                      <span>{["♨", "☕", "⌂", "◇", "₩"][i]}</span>{style}{selectedStyles.includes(style) && <b>✓</b>}
                    </button>
                  ))}
                </div>
              </div>
              <div className="preference-card">
                <div className="pref-title"><span>02</span><b>누구와 떠나나요?</b></div>
                <div className="companion-options">
                  {companions.map((item, i) => <button key={item} className={`companion-option ${companion === item ? "selected" : ""}`} onClick={() => setCompanion(item)}><span>{["♙", "♡", "♧", "⌂"][i]}</span>{item}</button>)}
                </div>
              </div>
            </div>
          </section>

          <section className="destination-section" id="how-it-works">
            <div className="section-heading compact"><div><span className="section-kicker">START EXPLORING</span><h2>요즘 떠나고 싶은 도시</h2></div><span className="subtle-link">영감이 필요할 때 <span>↗</span></span></div>
            <div className="destination-grid">
              {[
                { name: "오사카", country: "JAPAN · 일본", desc: "먹고, 걷고, 발견하는 재미", img: "photo-1590559899731-a382839e5549" },
                { name: "도쿄", country: "JAPAN · 일본", desc: "도시의 리듬에 빠져들기", img: "photo-1540959733332-eab4deabeeaf" },
                { name: "타이베이", country: "TAIWAN · 대만", desc: "골목마다 새로운 맛", img: "photo-1470004914212-05527e49370b" },
                { name: "파리", country: "FRANCE · 프랑스", desc: "느리게 즐기는 낭만", img: "photo-1502602898657-3e91760cbb34" }
              ].map((city) => <button className="destination-card" key={city.name} onClick={() => { setDestination(city.name); setShowResults(true); setNotice(`${city.name} 미리보기로 이동했어요.`); }}>
                <img src={`https://images.unsplash.com/${city.img}?auto=format&fit=crop&w=800&q=85`} alt={`${city.name} 여행`} />
                <span className="destination-overlay" /><span className="destination-meta">{city.country}</span><b>{city.name}</b><small>{city.desc}</small><span className="destination-arrow">↗</span>
              </button>)}
            </div>
          </section>
          <footer className="footer"><a className="brand small" href="#"><span className="brand-mark">✳</span><span className="brand-word">trip<span>vlog</span></span></a><span>여행은 더 가볍게, 발견은 더 깊게.</span><span>© 2026 tripvlog</span></footer>
        </main>
      ) : (
        <main className="results-page">
          <div className="results-heading">
            <div><div className="breadcrumb">여행지 탐색 <span>/</span> 분석 결과</div><h1><span className="heading-pin">⌖</span> {destination || "오사카"} <span className="heading-sub">브이로그 지도</span></h1><p>여행 브이로그에서 찾은 장소와 방문 근거를 한눈에 확인하세요.</p></div>
            <button className="outline-button" onClick={() => setShowResults(false)}>← 다른 여행지 찾기</button>
          </div>
          <div className="result-summary">
            <div className="summary-item"><span className="summary-icon">▶</span><div><small>분석한 영상</small><b>5개 채널</b></div></div>
            <div className="summary-divider" />
            <div className="summary-item"><span className="summary-icon">⌖</span><div><small>방문 확인 장소</small><b>18곳 <i>+12%</i></b></div></div>
            <div className="summary-divider" />
            <div className="summary-item"><span className="summary-icon">◷</span><div><small>영상 근거가 연결된 장소</small><b>14곳</b></div></div>
            <div className="summary-note"><span className="green-dot" /> 분석 완료 <span>·</span> 일부 영상의 분석 결과를 바탕으로 한 UI 미리보기</div>
          </div>

          <div className="mobile-view-toggle"><button className={mobileTab === "places" ? "selected" : ""} onClick={() => setMobileTab("places")}>장소 목록</button><button className={mobileTab === "map" ? "selected" : ""} onClick={() => setMobileTab("map")}>지도 보기</button></div>
          <div className="results-layout">
            <section className={`places-panel ${mobileTab === "map" ? "mobile-hidden" : ""}`}>
              <div className="panel-title-row"><div><span className="section-kicker">DISCOVERED PLACES</span><h2>발견한 장소 <span>{filteredPlaces.length}</span></h2></div><button className="sort-button" onClick={() => setNotice("방문 채널 수가 많은 순으로 정렬되어 있어요.")}>방문 채널 순⌄</button></div>
              <div className="filter-row">{styles.map((style) => <button key={style} className={activeFilter === style ? "filter-chip active" : "filter-chip"} onClick={() => setActiveFilter(style)}>{style}</button>)}</div>
              <div className="place-list">
                {filteredPlaces.map((place, index) => <article key={place.id} className={`place-card ${selectedPlace.id === place.id ? "focused" : ""}`} onClick={() => { setSelectedPlace(place); setMobileTab("map"); }}>
                  <div className="place-image"><img src={place.image} alt={place.name} /><span className="place-number">{String(index + 1).padStart(2, "0")}</span><button aria-label="장소 저장" className={`save-button ${saved.includes(place.id) ? "saved" : ""}`} onClick={(e) => { e.stopPropagation(); toggleSaved(place.id); }}>{saved.includes(place.id) ? "♥" : "♡"}</button></div>
                  <div className="place-content"><div className="place-topline"><span className="category-label">{place.category}</span><span className="place-area">⌖ {place.area}</span></div><h3>{place.name}</h3><div className="visit-count"><span className="mini-avatars"><i>여</i><i>행</i><i>자</i></span><b>{place.visits}개 채널</b>에서 방문 확인</div><div className="sentiment-row"><span className="sentiment positive">긍정 {place.positive}</span>{place.negative > 0 && <span className="sentiment negative">불만 {place.negative}</span>}<span className="evidence-time">◷ {place.time}</span></div><button className="evidence-link" onClick={(e) => { e.stopPropagation(); setSelectedPlace(place); setNotice(`${place.channel} 영상 ${place.videoTime} 근거를 선택했어요.`); }}>영상 근거 보기 <span>↗</span></button></div>
                </article>)}
                {filteredPlaces.length === 0 && <div className="empty-state">이 카테고리에 해당하는 장소가 아직 없어요.</div>}
              </div>
              <p className="panel-disclaimer">장소 집계는 이번 분석에서 확인된 채널 기준이며, 전체 여행자의 선호도를 의미하지 않습니다.</p>
            </section>

            <section className={`map-panel ${mobileTab === "places" ? "mobile-hidden" : ""}`}>
              <div className="map-toolbar"><div><b>OSAKA, JAPAN</b><span>장소 위치 탐색</span></div><button onClick={() => setNotice("실제 Google 지도 연결은 Maps API 키 설정 후 활성화됩니다.")}>↗ 지도 크게 보기</button></div>
              <div className="map-canvas">
                <div className="map-grid-lines" />
                <svg className="map-art" viewBox="0 0 700 650" preserveAspectRatio="xMidYMid slice" aria-label="오사카 지역 지도 미리보기">
                  <rect width="700" height="650" fill="#edf0e7"/>
                  <path d="M-20 120 C100 160 100 230 220 215 S350 100 430 160 S560 270 740 215 L740 275 C560 330 500 240 430 220 S280 280 210 275 S90 205 -20 180Z" fill="#d2e6e0"/>
                  <path d="M-40 490 C100 430 180 500 270 430 S440 410 510 470 S650 500 750 440" stroke="#c4ddd5" strokeWidth="38" fill="none"/>
                  <g stroke="#fff" strokeWidth="11" fill="none" opacity=".95"><path d="M20 70 L210 190 L300 330 L450 380 L680 580"/><path d="M100 0 L180 180 L160 350 L250 650"/><path d="M450 0 L410 170 L480 300 L440 480 L520 650"/><path d="M0 350 L160 330 L300 370 L430 300 L700 330"/><path d="M0 570 L180 510 L300 530 L420 450 L700 500"/><path d="M280 0 L320 150 L300 330 L350 500 L340 650"/></g>
                  <g stroke="#d5d8ce" strokeWidth="2" fill="none"><path d="M0 90 L180 130 L260 90 L390 130 L540 80 L700 110"/><path d="M20 250 L120 220 L240 270 L330 230 L550 260 L700 230"/><path d="M30 420 L150 390 L260 420 L360 390 L560 430 L700 400"/><path d="M80 0 L90 150 L60 300 L100 450 L70 650"/><path d="M560 0 L590 180 L550 320 L600 470 L570 650"/></g>
                  <g fill="#e3e6db" stroke="#d8ddd1" strokeWidth="1"><rect x="225" y="85" width="72" height="44" rx="5"/><rect x="475" y="90" width="80" height="58" rx="5"/><rect x="70" y="285" width="62" height="40" rx="5"/><rect x="520" y="360" width="85" height="50" rx="5"/><rect x="220" y="475" width="68" height="44" rx="5"/></g>
                  <path d="M205 140 C260 190 320 260 350 330 S440 420 490 480" stroke="#9abcb2" strokeWidth="4" strokeDasharray="7 8" fill="none"/>
                  <g fontSize="13" fontWeight="600" fill="#8c9589"><text x="45" y="205">SHINSAIBASHI</text><text x="460" y="210">OSAKA CASTLE</text><text x="510" y="540">NIPPONBASHI</text><text x="90" y="450">NAMBA</text><text x="300" y="90">UMEDA</text></g>
                  <g transform="translate(280 285)"><circle r="29" fill="#1f493b" opacity=".12"/><circle r="21" fill="#1f493b" stroke="white" strokeWidth="4"/><text textAnchor="middle" y="6" fontSize="19" fill="white">✳</text></g>
                  <g transform="translate(190 185)" className="map-pin"><path d="M0 0 C-18 -20 -16 -38 0 -42 C16 -38 18 -20 0 0Z" fill="#f07e60" stroke="white" strokeWidth="3"/><circle cy="-27" r="5" fill="white"/><rect x="15" y="-53" width="90" height="26" rx="13" fill="white"/><text x="60" y="-36" textAnchor="middle" fontSize="11" fill="#253c32" fontWeight="700">이치란 라멘</text></g>
                  <g transform="translate(430 355)"><path d="M0 0 C-18 -20 -16 -38 0 -42 C16 -38 18 -20 0 0Z" fill="#1f493b" stroke="white" strokeWidth="3"/><circle cy="-27" r="5" fill="white"/></g>
                  <g transform="translate(365 455)"><path d="M0 0 C-18 -20 -16 -38 0 -42 C16 -38 18 -20 0 0Z" fill="#1f493b" stroke="white" strokeWidth="3"/><circle cy="-27" r="5" fill="white"/></g>
                  <g transform="translate(520 275)"><path d="M0 0 C-18 -20 -16 -38 0 -42 C16 -38 18 -20 0 0Z" fill="#1f493b" stroke="white" strokeWidth="3"/><circle cy="-27" r="5" fill="white"/></g>
                </svg>
                <div className="map-zoom"><button onClick={() => setNotice("확대는 Google Maps 연결 후 지원됩니다.")}>＋</button><button onClick={() => setNotice("축소는 Google Maps 연결 후 지원됩니다.")}>−</button></div>
                <div className="map-legend"><span><i className="legend-confirmed" /> 방문 확인</span><span><i className="legend-selected" /> 선택한 장소</span></div>
                <div className="map-attribution">Map preview · Google Maps 연동 예정</div>
              </div>
              <div className="selected-evidence">
                <div className="evidence-head"><div><span className="section-kicker">VIDEO EVIDENCE</span><h3>{selectedPlace.name}</h3></div><span className="confirmed-pill">✓ 방문 확인</span></div>
                <div className="evidence-quote">“{selectedPlace.evidence}”</div>
                <div className="video-source"><div className="youtube-icon">▶</div><div className="video-info"><b>{selectedPlace.channel}</b><span>한국어 여행 브이로그 · {selectedPlace.videoTime}</span></div><button onClick={() => setNotice(`${selectedPlace.channel} 영상의 ${selectedPlace.videoTime} 지점으로 이동하려면 실제 영상 URL 연동이 필요합니다.`)}>영상 시점 보기 ↗</button></div>
                <div className="evidence-foot"><span>근거 유형: 음성 · 화면 자막</span><span>장소 평가: <b className="text-green">긍정</b> / 대기 <b className="text-red">부정</b></span></div>
              </div>
            </section>
          </div>
        </main>
      )}
      {notice && <div className="toast" role="status"><span>✳</span>{notice}<button onClick={() => setNotice("")} aria-label="닫기">×</button></div>}
    </div>
  );
}

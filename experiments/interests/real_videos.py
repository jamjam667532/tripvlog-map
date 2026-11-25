"""실제 YouTube 영상 정보로 영상 글 구성 비교 (결정 0011). 키는 출력하지 않는다."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.clients.embeddings import GatewayEmbedder
from shared.clients.youtube import YouTubeDataApi
from shared.rules.interests import clean_description, interest_text, mean_vector, theme_score
from shared.schemas.items import UserInterest

env = dict(
    x.split("=", 1)
    for x in Path(sys.argv[1]).read_text().splitlines()
    if "=" in x and not x.startswith("#")
)


def g(k: str) -> str:
    return env[k].strip().strip("'\"")


yt = YouTubeDataApi(g("YOUTUBE_API_KEY"))
emb = GatewayEmbedder(
    "bedrock-titan-embed-v2", api_key=g("LLM_API_KEY"), base_url=g("LLM_BASE_URL")
)

after = datetime.now(UTC) - timedelta(days=730)
ids = []
for q in ["도쿄 건축 투어", "도쿄 브이로그", "아키하바라 애니 성지순례"]:
    ids += yt.search(q, order="relevance", published_after=after, max_results=10)
ids = list(dict.fromkeys(ids))
metas = yt.videos(ids)
tagged = sum(bool(m.tags) for m in metas)
print(f"영상 {len(metas)}개 · YouTube {yt.units_used} unit · 태그 있는 영상 {tagged}개")

groups = {
    "건축": (
        0.47,
        ["건축 투어", "건축 답사 여행", "현대 건축 명소"],
        [
            "건축학개론 TV 현대 건축물과 건축가 이야기",
            "Archi Walk 안도 다다오, 쿠마 켄고 건축 답사",
            "안도 다다오 빛의 교회 답사 브이로그",
            "롯폰기 힐즈 건축 투어",
            "도시탐험가 랜드마크 건축과 도시계획 이야기",
        ],
    ),
    "애니": (
        0.27,
        ["애니 성지순례", "오타쿠 여행", "피규어 쇼핑 투어"],
        [
            "애니 리뷰왕 신작 애니메이션 리뷰와 추천",
            "오타쿠의 하루 피규어 언박싱, 애니 굿즈",
            "아키하바라 피규어 쇼핑 하울",
        ],
    ),
    "역사": (
        0.20,
        ["역사 여행", "박물관 투어", "고성 답사"],
        ["역사채널 e 한국사와 세계사를 5분 만에", "에도 시대 역사 한 번에 정리"],
    ),
}
interests = []
for k, (w, terms, ev) in groups.items():
    interests.append(
        UserInterest(
            label=k,
            weight=w,
            search_terms=terms,
            evidence_ids=["x"],
            embedding=mean_vector(emb.embed([interest_text(k, terms), *ev])),
        )
    )

variants = {
    "1 제목만": lambda m: m.title,
    "2 제목+설명 원문": lambda m: f"{m.title}\n{m.description[:300]}",
    "3 제목+정리 설명+태그": lambda m: "\n".join(
        p for p in [m.title, clean_description(m.description)[:300], " ".join(m.tags[:15])] if p
    ),
}
results = {}
for name, fn in variants.items():
    texts = [fn(m) for m in metas]
    vecs = emb.embed(texts)
    results[name] = {
        m.video_id: theme_score(v, interests, t) for m, v, t in zip(metas, vecs, texts, strict=True)
    }

print("\n점수(관심사) — 0.25 이상이면 관심사 영상으로 선택")
print(f"{'제목':<44} | " + " | ".join(f"{n:<18}" for n in variants))
for m in sorted(metas, key=lambda m: -results["3 제목+정리 설명+태그"][m.video_id][1]):
    cells = []
    for n in variants:
        label, s = results[n][m.video_id]
        cells.append(f"{'✔' if s >= 0.25 else ' '}{s:.2f} {label or '-':<12}")
    print(f"{m.title[:42]:<44} | " + " | ".join(cells))
for n in variants:
    picked = sum(1 for _, s in results[n].values() if s >= 0.25)
    print(f"{n}: 선택 {picked}/{len(metas)}")
print(f"임베딩 토큰 {emb.tokens_used}")

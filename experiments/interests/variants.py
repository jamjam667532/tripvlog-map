"""관심사 벡터 개선안 비교. 앞 시험의 관심사를 그대로 쓰고(Bedrock 다시 안 부름) 임베딩만 다시."""

import re
import sys
from pathlib import Path

from shared.clients.embeddings import GatewayEmbedder
from shared.rules.interests import cosine, interest_text

env = dict(
    line.split("=", 1)
    for line in Path(sys.argv[1]).read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
emb = GatewayEmbedder(
    "bedrock-titan-embed-v2",
    api_key=env["LLM_API_KEY"].strip().strip("'\""),
    base_url=env["LLM_BASE_URL"].strip().strip("'\""),
)

interests = {  # 앞 시험의 검증 결과 그대로
    "건축": (
        0.47,
        ["건축 투어", "건축 답사 여행", "현대 건축 명소"],
        [
            "건축학개론 TV 현대 건축물과 건축가 이야기를 쉽게 풀어드립니다",
            "공간 읽어주는 남자 도시와 건축, 공간 디자인 리뷰",
            "Archi Walk Architecture walks around the world. 안도 다다오, 쿠마 켄고 건축 답사",
            "인테리어 클래스 집과 공간 인테리어, 건축 디자인 강의",
            "도시탐험가 랜드마크 건축과 도시계획 이야기",
            "안도 다다오 빛의 교회 답사 브이로그",
            "롯폰기 힐즈 건축 투어",
        ],
    ),
    "애니메이션·오타쿠 문화": (
        0.27,
        ["애니 성지순례", "오타쿠 여행", "피규어 쇼핑 투어"],
        [
            "애니 리뷰왕 신작 애니메이션 리뷰와 추천",
            "오타쿠의 하루 피규어 언박싱, 애니 굿즈, 코믹마켓 후기",
            "성우 덕질 채널 일본 성우와 애니 OST 이야기",
            "아키하바라 피규어 쇼핑 하울",
        ],
    ),
    "역사": (
        0.20,
        ["역사 여행", "박물관 투어", "고성 답사"],
        [
            "역사채널 e 한국사와 세계사를 5분 만에",
            "썬킴의 세계사 재미있는 세계사 이야기",
            "에도 시대 역사 한 번에 정리",
        ],
    ),
    "인문·미술": (
        0.07,
        ["미술관 여행", "인문 산책"],
        ["교양 한 스푼 인문학, 철학, 미술사 교양 강의"],
    ),
}
candidates = {
    "도쿄 건축 투어 | 안도 다다오와 쿠마 켄고 건축물 따라 걷기": "건축",
    "도쿄 현대건축 산책 브이로그 오모테산도": "건축",
    "도쿄 국립박물관 에도 시대 유물 관람기": "역사",
    "아키하바라 애니 성지순례 굿즈 쇼핑": "애니메이션·오타쿠 문화",
    "도쿄 라멘 맛집 5곳 먹방": None,
    "신주쿠 이자카야 술집 투어": None,
    "도쿄 디즈니랜드 하루 코스": None,
    "시부야 카페 투어 감성 브이로그": None,
}
cv = dict(zip(candidates, emb.embed(list(candidates)), strict=False))
base = {
    k: v
    for k, v in zip(
        interests,
        emb.embed([interest_text(k, t) for k, (_, t, _) in interests.items()]),
        strict=False,
    )
}
evid = {}
for k, (_, _, texts) in interests.items():
    vs = emb.embed(texts)
    evid[k] = vs


def mean(vs):
    return [sum(x) / len(vs) for x in zip(*vs, strict=False)]


def tokens(terms):
    out = set()
    for t in terms:
        out |= {
            w
            for w in re.split(r"\s+", t)
            if len(w) >= 2 and w not in {"여행", "투어", "명소", "답사"}
        }
    return out


def run(name, vecs, factor, lexical):
    print(f"\n■ {name}")
    good = 0
    for text, expect in candidates.items():
        best = (None, 0.0)
        for k, (w, terms, _) in interests.items():
            s = cosine(cv[text], vecs[k]) * factor(w)
            if lexical and any(tok in text for tok in tokens(terms)):
                s += 0.15
            if s > best[1]:
                best = (k, s)
        picked = best[1] >= 0.25
        ok = (picked and best[0] == expect) or (not picked and expect is None)
        good += ok
        mark, choice = ("✔" if ok else "✘"), ("선택" if picked else "제외")
        print(f"  {mark} {best[1]:.3f} [{best[0]}] {choice} | {text}")
    print(f"  → 맞음 {good}/{len(candidates)}")


run("지금 방식 (짧은 문장, 보정 0.6+0.4w)", base, lambda w: 0.6 + 0.4 * w, False)
centroid = {k: mean([base[k], *evid[k]]) for k in interests}
run("A. 근거 평균 벡터 (보정 0.8+0.2w)", centroid, lambda w: 0.8 + 0.2 * w, False)
run("A+B. 근거 평균 + 검색어 단어 일치 +0.15", centroid, lambda w: 0.8 + 0.2 * w, True)
print(f"\n임베딩 토큰 {emb.tokens_used}")

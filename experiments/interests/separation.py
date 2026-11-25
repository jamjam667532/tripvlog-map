"""관심사 벡터끼리 얼마나 떨어져 있나 (근거 평균 벡터). 키는 출력하지 않는다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shared.clients.embeddings import GatewayEmbedder
from shared.rules.interests import cosine, interest_text, mean_vector

env = dict(
    x.split("=", 1)
    for x in Path(sys.argv[1]).read_text().splitlines()
    if "=" in x and not x.startswith("#")
)
emb = GatewayEmbedder(
    "bedrock-titan-embed-v2",
    api_key=env["LLM_API_KEY"].strip().strip("'\""),
    base_url=env["LLM_BASE_URL"].strip().strip("'\""),
)
groups = {
    "건축": (
        ["건축 투어", "건축 답사 여행", "현대 건축 명소"],
        [
            "건축학개론 TV 현대 건축물과 건축가 이야기",
            "공간 읽어주는 남자 도시와 건축, 공간 디자인 리뷰",
            "Archi Walk 안도 다다오, 쿠마 켄고 건축 답사",
            "안도 다다오 빛의 교회 답사 브이로그",
            "롯폰기 힐즈 건축 투어",
        ],
    ),
    "애니": (
        ["애니 성지순례", "오타쿠 여행", "피규어 쇼핑 투어"],
        [
            "애니 리뷰왕 신작 애니메이션 리뷰와 추천",
            "오타쿠의 하루 피규어 언박싱, 애니 굿즈",
            "성우 덕질 채널 일본 성우와 애니 OST",
            "아키하바라 피규어 쇼핑 하울",
        ],
    ),
    "역사": (
        ["역사 여행", "박물관 투어", "고성 답사"],
        [
            "역사채널 e 한국사와 세계사를 5분 만에",
            "썬킴의 세계사 재미있는 세계사 이야기",
            "에도 시대 역사 한 번에 정리",
        ],
    ),
    "인문·미술": (["미술관 여행", "인문 산책"], ["교양 한 스푼 인문학, 철학, 미술사 교양 강의"]),
}
vec = {}
for k, (terms, ev) in groups.items():
    vec[k] = mean_vector(emb.embed([interest_text(k, terms), *ev]))
names = list(vec)
print("관심사 벡터끼리 코사인 유사도 (1=같음, 0=무관)\n")
print(" " * 10 + "".join(f"{n:>10}" for n in names))
for a in names:
    print(f"{a:<10}" + "".join(f"{cosine(vec[a], vec[b]):>10.2f}" for b in names))
print(f"\n임베딩 토큰 {emb.tokens_used}")

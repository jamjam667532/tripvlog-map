"""관심사 추출·임베딩 품질 시험 (결정 0011).

예시 구독 목록 → 실제 학교 게이트웨이. 키는 출력하지 않는다.
"""

import sys
import time
from pathlib import Path

from shared.clients.bedrock import GatewayChat
from shared.clients.embeddings import GatewayEmbedder
from shared.clients.interests import GatewayInterestExtractor
from shared.rules.interests import cosine, interest_text, theme_score, validate_interests
from shared.schemas.items import UserInterest
from shared.schemas.taste import ChannelInfo, ChannelVideo

env = dict(
    line.split("=", 1)
    for line in Path(sys.argv[1]).read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
key = env["LLM_API_KEY"].strip().strip("'\"")
base = env["LLM_BASE_URL"].strip().strip("'\"")


def ch(i, t, d):
    return ChannelInfo(channel_id=f"UC{i:03d}", title=t, description=d)


channels = [
    # 건축 5
    ch(1, "건축학개론 TV", "현대 건축물과 건축가 이야기를 쉽게 풀어드립니다"),
    ch(2, "공간 읽어주는 남자", "도시와 건축, 공간 디자인 리뷰"),
    ch(3, "Archi Walk", "Architecture walks around the world. 안도 다다오, 쿠마 켄고 건축 답사"),
    ch(4, "인테리어 클래스", "집과 공간 인테리어, 건축 디자인 강의"),
    ch(5, "도시탐험가", "랜드마크 건축과 도시계획 이야기"),
    # 역사·교양 3
    ch(6, "역사채널 e", "한국사와 세계사를 5분 만에"),
    ch(7, "썬킴의 세계사", "재미있는 세계사 이야기"),
    ch(8, "교양 한 스푼", "인문학, 철학, 미술사 교양 강의"),
    # 애니 4
    ch(9, "애니 리뷰왕", "신작 애니메이션 리뷰와 추천"),
    ch(10, "오타쿠의 하루", "피규어 언박싱, 애니 굿즈, 코믹마켓 후기"),
    ch(11, "성우 덕질 채널", "일본 성우와 애니 OST 이야기"),
    ch(12, "만화 읽어주는 형", "만화책 리뷰와 웹툰 이야기"),
    # 관계없음
    ch(13, "롤 프로 하이라이트", "LCK 경기 하이라이트"),
    ch(14, "코딩하는 개발자", "파이썬, 자바스크립트 강의"),
    ch(15, "재테크 연구소", "주식과 부동산 투자"),
    ch(16, "오늘의 운동", "홈트레이닝 루틴"),
]
liked = [
    ChannelVideo(
        video_id="vid00001", channel_id="UC003", title="안도 다다오 빛의 교회 답사 브이로그"
    ),
    ChannelVideo(video_id="vid00002", channel_id="UC005", title="롯폰기 힐즈 건축 투어"),
    ChannelVideo(video_id="vid00003", channel_id="UC010", title="아키하바라 피규어 쇼핑 하울"),
    ChannelVideo(video_id="vid00004", channel_id="UC007", title="에도 시대 역사 한 번에 정리"),
    ChannelVideo(video_id="vid00005", channel_id="UC013", title="롤드컵 결승 명장면"),
]

chat = GatewayChat("bedrock-haiku", api_key=key, base_url=base)
t0 = time.time()
proposals = GatewayInterestExtractor(chat).extract(channels, liked)
t1 = time.time()
print(f"■ Bedrock 제안 {len(proposals)}개 ({t1 - t0:.1f}초)")
for p in proposals:
    print(f"  - {p.label}: 근거 {p.evidence_ids} / 검색어 {p.search_terms}")
known = {c.channel_id for c in channels} | {v.video_id for v in liked}
valid = validate_interests(proposals, known)
print(f"\n■ 검증 후 {len(valid)}개")
for v in valid:
    print(f"  - {v.label} 비중 {v.weight} / 근거 {len(v.evidence_ids)}개 / 검색어 {v.search_terms}")

emb = GatewayEmbedder("bedrock-titan-embed-v2", api_key=key, base_url=base)
vecs = emb.embed([interest_text(v.label, v.search_terms) for v in valid])
interests = [
    UserInterest(
        label=v.label,
        weight=v.weight,
        search_terms=v.search_terms,
        evidence_ids=v.evidence_ids,
        embedding=e,
    )
    for v, e in zip(valid, vecs, strict=False)
]

candidates = [
    "도쿄 건축 투어 | 안도 다다오와 쿠마 켄고 건축물 따라 걷기",
    "도쿄 현대건축 산책 브이로그 오모테산도",
    "도쿄 국립박물관 에도 시대 유물 관람기",
    "아키하바라 애니 성지순례 굿즈 쇼핑",
    "도쿄 라멘 맛집 5곳 먹방",
    "신주쿠 이자카야 술집 투어",
    "도쿄 디즈니랜드 하루 코스",
    "시부야 카페 투어 감성 브이로그",
]
cvecs = emb.embed(candidates)
print(f"\n■ 후보 영상 점수 (관심사 x 유사도, 기준 0.25) / 임베딩 토큰 {emb.tokens_used}")
rows = []
for text, v in zip(candidates, cvecs, strict=False):
    label, score = theme_score(v, interests)
    raw = {i.label: round(cosine(v, i.embedding), 3) for i in interests}
    rows.append((score, label, text, raw))
for score, label, text, raw in sorted(rows, key=lambda r: -r[0]):
    mark = "✔" if score >= 0.25 else " "
    print(f"  {mark} {score:.3f} [{label}] {text}\n      원유사도 {raw}")

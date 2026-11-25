"""[M8] api_me: 로그인 사용자의 선호와 유튜브 연결 (spec §3.3, 결정 0010).

HTTP API 페이로드 2.0.

사용자는 JWT Authorizer가 검증한 토큰의 sub로만 정한다(google:<sub>).
요청 본문의 userId는 받지 않는다.

GET    /me/preferences          선호와 유튜브 연결 상태
PATCH  /me/preferences          선호 수정. 참고 채널은 지금 선호나 유튜브 후보 안에서만
POST   /me/youtube/import       X-Google-Access-Token으로 구독·좋아요를 한 번 읽어
                                취향 프로필(구독 여행 채널 + 스타일 비율)을 자동으로 만든다
POST   /me/youtube/confirm      자동 프로필을 사용자가 고친다(고친 값이 우선)
DELETE /me/youtube/connection   유튜브에서 온 데이터만 지운다

액세스 토큰은 요청 중에만 쓰고 저장·로그하지 않는다(확정 결정 3).
채널 이름·영상 제목은 응답에만 쓰고 저장하지 않는다.
라벨은 Bedrock 제안 → 근거 확인(원문에 없으면 UNKNOWN)을 거쳐
자동 프로필에 들어간다(결정 0010 개정).
"""

import base64
import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ValidationError

from functions.job_api import Unauthorized, user_id_of
from shared.clients.bedrock import GatewayChat
from shared.clients.embeddings import Embedder, GatewayEmbedder
from shared.clients.errors import ExternalApiError
from shared.clients.interests import GatewayInterestExtractor, InterestExtractor
from shared.clients.secrets import (
    SECRET_LLM_API_KEY,
    SECRET_LLM_BASE_URL,
    SECRET_YOUTUBE,
    get_secret,
)
from shared.clients.taste import LABEL_VERSION, GatewayTasteLabeler, TasteLabeler
from shared.clients.youtube import (
    YouTubeClient,
    YouTubeDataApi,
    YouTubeUserApi,
    YouTubeUserClient,
)
from shared.repos import Repos
from shared.rules.interests import interest_text, validate_interests
from shared.rules.taste import (
    accept_label,
    auto_travel_channels,
    combined_style_profile,
    travel_candidates,
)
from shared.schemas.api import ErrorBody, ErrorResponse
from shared.schemas.items import UserInterest, UserItem, UserPreferences, YoutubeLink
from shared.schemas.taste import (
    ChannelInfo,
    ChannelTasteLabel,
    ChannelVideo,
    InterestView,
    MeResponse,
    TasteChannelCandidate,
    YoutubeImportResponse,
)
from shared.settings import Settings, require

logger = logging.getLogger(__name__)

ACCESS_TOKEN_HEADER = "x-google-access-token"
MAX_CHANNELS_CHECKED = 250  # 구독 200 + 좋아요 영상의 채널
MAX_TRAVEL_CHANNELS = 50  # 취향 프로필에 담는 구독 여행 채널 상한
MAX_INTEREST_CHANNELS = 200  # 관심사 추출에 보내는 구독 채널 상한(결정 0011)


@dataclass(frozen=True)
class Deps:
    settings: Settings
    repos: Repos
    youtube: YouTubeClient
    youtube_for: Callable[[str], YouTubeUserClient]  # 액세스 토큰 → 사용자 조회 클라이언트
    labeler: TasteLabeler
    extractor: InterestExtractor  # 결정 0011: 구독·좋아요 전체에서 관심사 제안
    embedder: Embedder
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def _response(status: int, body: BaseModel) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": body.model_dump_json(exclude_none=True),
    }


def _error(status: int, code: str, message: str) -> dict[str, Any]:
    return _response(status, ErrorResponse(error=ErrorBody(code=code, message=message)))


def _body(event: dict[str, Any]) -> Any:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    return json.loads(raw or "{}")


def _interest_views(
    interests: list[UserInterest], hidden: list[str], titles: dict[str, str] | None = None
) -> list[InterestView]:
    """화면용 관심사. 근거 제목은 연결 직후 응답에만 있다(저장하지 않으므로 이후 조회에는 없다)."""
    titles = titles or {}
    return [
        InterestView(
            label=i.label,
            weight=i.weight,
            search_terms=list(i.search_terms),
            evidence_titles=[titles[e] for e in i.evidence_ids if e in titles][:3],
            hidden=i.label in hidden,
        )
        for i in interests
    ]


def _me(user: UserItem) -> MeResponse:
    yt = user.youtube
    return MeResponse(
        preferences=user.preferences,
        youtube_linked=bool(yt and yt.linked),
        synced_at=yt.synced_at if yt else None,
        resync_due_at=yt.resync_due_at if yt else None,
        travel_channel_ids=list(yt.travel_channel_ids) if yt else [],
        style_profile_candidate=dict(yt.style_profile_candidate) if yt else {},
        interests=_interest_views(list(yt.interests), user.preferences.hidden_interests)
        if yt
        else [],
    )


def _save_preferences(
    event: dict[str, Any], user: UserItem, deps: Deps, *, from_candidates_only: bool
) -> dict[str, Any]:
    try:
        prefs = UserPreferences.model_validate(_body(event))
    except (ValueError, ValidationError):
        return _error(400, "INVALID_REQUEST", "request body is invalid")
    allowed = set(user.youtube.travel_channel_ids) if user.youtube else set()
    if not from_candidates_only:
        allowed |= set(user.preferences.reference_channel_ids)
    if not set(prefs.reference_channel_ids) <= allowed:
        return _error(400, "UNKNOWN_CHANNEL", "reference channels must come from the candidates")
    updated = user.model_copy(update={"preferences": prefs})
    deps.repos.users.put(updated)
    return _response(200, _me(updated))


def get_preferences(event: dict[str, Any], user_id: str, deps: Deps) -> dict[str, Any]:
    return _response(200, _me(deps.repos.users.get_or_new(user_id)))


def patch_preferences(event: dict[str, Any], user_id: str, deps: Deps) -> dict[str, Any]:
    user = deps.repos.users.get_or_new(user_id)
    return _save_preferences(event, user, deps, from_candidates_only=False)


def confirm_youtube(event: dict[str, Any], user_id: str, deps: Deps) -> dict[str, Any]:
    user = deps.repos.users.get(user_id)
    if user is None or user.youtube is None:
        return _error(409, "NOT_LINKED", "import youtube first")
    return _save_preferences(event, user, deps, from_candidates_only=True)


def delete_connection(event: dict[str, Any], user_id: str, deps: Deps) -> dict[str, Any]:
    if deps.repos.users.get(user_id) is not None:
        deps.repos.users.remove_youtube(user_id)
    return _response(200, _me(deps.repos.users.get_or_new(user_id)))


def _interests(
    infos: list[ChannelInfo], liked: list[ChannelVideo], deps: Deps
) -> list[UserInterest]:
    """관심사: Bedrock 제안 → 근거 검증(입력에 있는 ID만) → 임베딩. 실패하면 빈 목록으로 계속."""
    try:
        proposals = deps.extractor.extract(infos[:MAX_INTEREST_CHANNELS], liked)
        valid = validate_interests(
            proposals, {c.channel_id for c in infos} | {v.video_id for v in liked}
        )
        if not valid:
            return []
        vectors = deps.embedder.embed([interest_text(i.label, i.search_terms) for i in valid])
    except Exception:
        logger.exception("interest extraction failed")  # 채널 정보·토큰은 남기지 않는다
        return []
    return [
        UserInterest(
            label=i.label,
            weight=i.weight,
            search_terms=i.search_terms,
            evidence_ids=i.evidence_ids,
            embedding=vec,
        )
        for i, vec in zip(valid, vectors, strict=True)
    ]


def _labels(candidates: list[ChannelInfo], deps: Deps, now: int) -> dict[str, ChannelTasteLabel]:
    """채널 라벨: 캐시 먼저, 없는 채널만 Bedrock. 실패하면 UNKNOWN으로 두고 계속한다."""
    s = deps.settings
    cache = deps.repos.youtube_cache
    by_id = {c.channel_id: c for c in candidates}
    labels = cache.get_channel_tastes(list(by_id), version=LABEL_VERSION, now=now)
    missing = [c for c in candidates if c.channel_id not in labels]
    if missing:
        try:
            proposed = deps.labeler.label(missing)
        except Exception:
            logger.exception("taste labeling failed")  # 채널 정보·토큰은 남기지 않는다
            proposed = []
        for label in proposed:
            accepted = accept_label(label, by_id[label.channel_id])
            labels[label.channel_id] = accepted
            cache.put_channel_taste(
                accepted, version=LABEL_VERSION, now=now, ttl_days=s.youtube_cache_ttl_days
            )
    return labels


def import_youtube(event: dict[str, Any], user_id: str, deps: Deps) -> dict[str, Any]:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = headers.get(ACCESS_TOKEN_HEADER)
    if not token:
        return _error(400, "MISSING_TOKEN", "google access token header is required")

    now_dt = deps.clock()
    now = int(now_dt.timestamp())
    try:
        mine = deps.youtube_for(token)
        subscriptions = mine.subscription_channel_ids()
        liked = mine.liked_videos()
    except ExternalApiError as e:
        if e.status in (401, 403):
            return _error(401, "YOUTUBE_TOKEN_REJECTED", "youtube access was not granted")
        raise

    channel_ids = list(dict.fromkeys([*subscriptions, *(v.channel_id for v in liked)]))
    infos = deps.youtube.channels(channel_ids[:MAX_CHANNELS_CHECKED])
    candidates = travel_candidates(infos, liked)
    # API Gateway 30초 제한: 채널 라벨과 관심사 추출을 동시에 부른다
    with ThreadPoolExecutor(max_workers=2) as pool:
        labels_job = pool.submit(_labels, candidates, deps, now)
        interests_job = pool.submit(_interests, infos, liked, deps)
        labels, interests = labels_job.result(), interests_job.result()

    # 결정 0010 개정: 확인을 기다리지 않고 자동으로 취향 프로필을 만든다(화면에서 고칠 수 있다)
    travel = auto_travel_channels(labels, liked)[:MAX_TRAVEL_CHANNELS]
    profile = combined_style_profile(liked, labels)
    applied = set(travel)
    shown: list[TasteChannelCandidate] = []
    for c in candidates:
        label = labels.get(c.channel_id) or ChannelTasteLabel(
            channel_id=c.channel_id, travel="UNKNOWN"
        )
        if label.travel != "NO":  # 여행과 무관하다는 근거가 있는 채널은 보여 주지 않는다
            shown.append(
                TasteChannelCandidate(
                    channel_id=c.channel_id,
                    title=c.title,
                    travel=label.travel,
                    styles=list(label.styles),
                    evidence=label.evidence,
                    applied=c.channel_id in applied,
                )
            )

    titles = {c.channel_id: c.title for c in infos} | {v.video_id: v.title for v in liked}
    user = deps.repos.users.get_or_new(user_id)
    link = YoutubeLink(
        linked=True,
        synced_at=now_dt,
        resync_due_at=now_dt + timedelta(days=deps.settings.youtube_cache_ttl_days),
        travel_channel_ids=travel,  # 자동 취향 프로필: 구독 여행 채널
        liked_travel_video_ids=[],  # 결정 0010-3: 저장하지 않는다
        style_profile_candidate=profile,  # 자동 취향 프로필: 스타일 비율
        interests=interests,  # 결정 0011: 관심사(이름·비중·검색어·근거 ID·벡터)
    )
    deps.repos.users.put(user.model_copy(update={"youtube": link}))
    return _response(
        200,
        YoutubeImportResponse(
            channels=shown,
            style_profile=profile,
            interests=_interest_views(interests, user.preferences.hidden_interests, titles),
            subscriptions_checked=len(subscriptions),
            liked_checked=len(liked),
        ),
    )


ROUTES: dict[str, Callable[[dict[str, Any], str, Deps], dict[str, Any]]] = {
    "GET /me/preferences": get_preferences,
    "PATCH /me/preferences": patch_preferences,
    "POST /me/youtube/import": import_youtube,
    "POST /me/youtube/confirm": confirm_youtube,
    "DELETE /me/youtube/connection": delete_connection,
}


def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    route = ROUTES.get(event.get("routeKey", ""))
    if route is None:
        return _error(404, "NOT_FOUND", "route not found")
    try:
        user_id = user_id_of(event)
    except Unauthorized:
        return _error(401, "UNAUTHORIZED", "login required")
    try:
        return route(event, user_id, deps)
    except Exception:
        logger.exception("api_me failed")
        return _error(500, "INTERNAL", "internal error")


@lru_cache(maxsize=1)
def _deps() -> Deps:
    s = Settings.from_env()
    chat = GatewayChat(
        require(s.bedrock_interpreter_model_id, "BEDROCK_INTERPRETER_MODEL_ID"),
        api_key=get_secret(SECRET_LLM_API_KEY),
        base_url=get_secret(SECRET_LLM_BASE_URL),
    )
    return Deps(
        settings=s,
        repos=Repos.from_settings(s),
        youtube=YouTubeDataApi(get_secret(SECRET_YOUTUBE)),
        youtube_for=YouTubeUserApi,
        labeler=GatewayTasteLabeler(chat),
        extractor=GatewayInterestExtractor(chat),
        embedder=GatewayEmbedder(
            require(s.embedding_model_id, "EMBEDDING_MODEL_ID"),
            api_key=get_secret(SECRET_LLM_API_KEY),
            base_url=get_secret(SECRET_LLM_BASE_URL),
        ),
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return run(event, _deps())

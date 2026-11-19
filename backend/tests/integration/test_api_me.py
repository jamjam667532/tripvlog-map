"""[M8] api_me: 유튜브 취향 연결 (결정 0010). DynamoDB는 moto·Local, 외부 API는 가짜."""

import json
from typing import Any

import pytest

from functions.api_me.handler import Deps, run
from shared.clients.taste import LABEL_VERSION
from shared.repos import Repos
from shared.schemas.taste import ChannelInfo, ChannelTasteLabel, ChannelVideo
from shared.settings import Settings
from tests.fakes import FakeTasteLabeler, FakeYouTube, FakeYouTubeUser
from tests.integration.factories import NOW, NOW_EPOCH

TOKEN = "ya29.user-access-token"
SUB = "1234567890"

CHANNELS = [
    ChannelInfo(channel_id="trip", title="주말 해외여행", description="일본 소도시를 걷습니다"),
    ChannelInfo(channel_id="food", title="먹방왕", description="맛있는 것만"),
    ChannelInfo(channel_id="game", title="게임 방송", description=""),
]
LIKED = [
    ChannelVideo(video_id="l1", channel_id="food", title="오사카 맛집 투어"),
    ChannelVideo(video_id="l2", channel_id="food", title="도쿄 라멘 여행"),
    ChannelVideo(video_id="l3", channel_id="game", title="신작 리뷰"),
]
LABELS = {
    "trip": ChannelTasteLabel(
        channel_id="trip", travel="YES", styles=["관광·역사"], evidence="일본 소도시를 걷습니다"
    ),
    # 근거가 채널 글에 없다 → UNKNOWN으로 낮아져야 한다
    "food": ChannelTasteLabel(
        channel_id="food", travel="YES", styles=["맛집"], evidence="미식 여행"
    ),
}


def event(route: str, *, body: Any = None, token: str | None = None, sub: str | None = SUB) -> Any:
    ev: dict[str, Any] = {"routeKey": route, "headers": {}}
    if sub is not None:
        ev["requestContext"] = {"authorizer": {"jwt": {"claims": {"sub": sub}}}}
    if token is not None:
        ev["headers"]["x-google-access-token"] = token
    if body is not None:
        ev["body"] = json.dumps(body)
    return ev


def call(deps: Deps, ev: Any) -> tuple[int, dict[str, Any]]:
    resp = run(ev, deps)
    return resp["statusCode"], json.loads(resp["body"])


@pytest.fixture
def user_api() -> FakeYouTubeUser:
    return FakeYouTubeUser(["trip", "food", "game"], LIKED)


@pytest.fixture
def labeler() -> FakeTasteLabeler:
    return FakeTasteLabeler(LABELS)


@pytest.fixture
def deps(
    repos: Repos, settings: Settings, user_api: FakeYouTubeUser, labeler: FakeTasteLabeler
) -> Deps:
    return Deps(
        settings=settings,
        repos=repos,
        youtube=FakeYouTube({}, [], channels=CHANNELS),
        youtube_for=user_api.for_token,
        labeler=labeler,
        clock=lambda: NOW,
    )


def test_import_returns_candidates_and_stores_only_ids(
    deps: Deps, repos: Repos, user_api: FakeYouTubeUser, aws: Any, settings: Settings
) -> None:
    status, body = call(deps, event("POST /me/youtube/import", token=TOKEN))
    assert status == 200
    shown = {c["channelId"]: c for c in body["channels"]}
    assert set(shown) == {"food", "trip"}  # 게임 채널은 여행 후보가 아니다
    assert shown["trip"]["travel"] == "YES" and shown["trip"]["styles"] == ["관광·역사"]
    assert shown["food"]["travel"] == "UNKNOWN" and shown["food"]["styles"] == []
    assert body["styleProfile"] == {"맛집": 1.0}
    assert user_api.tokens == [TOKEN]

    user = repos.users.get("google:" + SUB)
    assert user is not None and user.youtube is not None
    assert set(user.youtube.travel_channel_ids) == {"food", "trip"}
    assert user.youtube.liked_travel_video_ids == []
    assert user.preferences.reference_channel_ids == []  # 확인 전에는 선호가 아니다

    # 토큰·채널 이름·영상 제목은 어느 테이블에도 저장되지 않는다
    dynamodb, _ = aws
    dump = json.dumps(
        [
            dynamodb.Table(t).scan()["Items"]
            for t in (settings.users_table, settings.youtube_cache_table)
        ],
        ensure_ascii=False,
        default=str,
    )
    for secret_or_name in (TOKEN, "주말 해외여행", "오사카 맛집 투어", "일본 소도시"):
        assert secret_or_name not in dump


def test_channel_labels_are_cached_per_channel(
    deps: Deps, repos: Repos, labeler: FakeTasteLabeler
) -> None:
    call(deps, event("POST /me/youtube/import", token=TOKEN))
    call(deps, event("POST /me/youtube/import", token=TOKEN, sub="someone-else"))
    assert labeler.asked == [["food", "trip"]]  # 두 번째 사용자는 캐시를 쓴다
    cached = repos.youtube_cache.get_channel_tastes(["trip"], version=LABEL_VERSION, now=NOW_EPOCH)
    assert cached["trip"].travel == "YES"


def test_labeler_failure_still_returns_unknown_candidates(
    repos: Repos, settings: Settings, user_api: FakeYouTubeUser
) -> None:
    deps = Deps(
        settings=settings,
        repos=repos,
        youtube=FakeYouTube({}, [], channels=CHANNELS),
        youtube_for=user_api.for_token,
        labeler=FakeTasteLabeler({}, fail=True),
        clock=lambda: NOW,
    )
    status, body = call(deps, event("POST /me/youtube/import", token=TOKEN))
    assert status == 200
    assert {c["travel"] for c in body["channels"]} == {"UNKNOWN"}


def test_import_needs_login_and_token(deps: Deps) -> None:
    assert call(deps, event("POST /me/youtube/import", token=TOKEN, sub=None))[0] == 401
    assert call(deps, event("POST /me/youtube/import"))[0] == 400


def test_rejected_youtube_token_is_401(repos: Repos, settings: Settings) -> None:
    deps = Deps(
        settings=settings,
        repos=repos,
        youtube=FakeYouTube({}, []),
        youtube_for=FakeYouTubeUser(reject=True).for_token,
        labeler=FakeTasteLabeler({}),
        clock=lambda: NOW,
    )
    status, body = call(deps, event("POST /me/youtube/import", token=TOKEN))
    assert status == 401 and body["error"]["code"] == "YOUTUBE_TOKEN_REJECTED"


def test_confirm_saves_only_candidate_channels(deps: Deps, repos: Repos) -> None:
    assert call(deps, event("POST /me/youtube/confirm", body={}))[0] == 409  # 연결 전
    call(deps, event("POST /me/youtube/import", token=TOKEN))

    bad = {"referenceChannelIds": ["game"], "styles": ["맛집"]}
    assert call(deps, event("POST /me/youtube/confirm", body=bad))[0] == 400

    ok = {"referenceChannelIds": ["trip"], "styles": ["맛집", "관광·역사"]}
    status, body = call(deps, event("POST /me/youtube/confirm", body=ok))
    assert status == 200
    assert body["preferences"]["referenceChannelIds"] == ["trip"]
    user = repos.users.get("google:" + SUB)
    assert user is not None and user.preferences.styles == ["맛집", "관광·역사"]


def test_body_user_id_is_rejected(deps: Deps) -> None:
    body = {"userId": "google:attacker", "styles": ["맛집"]}
    assert call(deps, event("PATCH /me/preferences", body=body))[0] == 400


def test_patch_can_keep_or_remove_channels_but_not_add_unknown(deps: Deps) -> None:
    call(deps, event("POST /me/youtube/import", token=TOKEN))
    call(deps, event("POST /me/youtube/confirm", body={"referenceChannelIds": ["trip"]}))
    assert call(deps, event("PATCH /me/preferences", body={"referenceChannelIds": []}))[0] == 200
    unknown = {"referenceChannelIds": ["somebody"]}
    assert call(deps, event("PATCH /me/preferences", body=unknown))[0] == 400


def test_delete_connection_removes_youtube_but_keeps_preferences(deps: Deps, repos: Repos) -> None:
    call(deps, event("POST /me/youtube/import", token=TOKEN))
    call(deps, event("POST /me/youtube/confirm", body={"referenceChannelIds": ["trip"]}))
    status, body = call(deps, event("DELETE /me/youtube/connection"))
    assert status == 200 and body["youtubeLinked"] is False
    user = repos.users.get("google:" + SUB)
    assert user is not None and user.youtube is None
    assert user.preferences.reference_channel_ids == ["trip"]


def test_get_preferences_for_new_user(deps: Deps) -> None:
    status, body = call(deps, event("GET /me/preferences"))
    assert status == 200 and body["youtubeLinked"] is False

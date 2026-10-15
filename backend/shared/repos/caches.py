"""CoordCache(Google 좌표 25일)와 YoutubeCache(검색·메타 25일, 일일 검색 횟수).

만료 판단은 읽을 때 expiresAt으로 한다. TTL 삭제는 늦을 수 있어 보조 수단이다.
"""

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from shared.repos.dynamo import batch_get, from_item, is_conditional_failure, to_item
from shared.schemas.items import (
    CoordCacheItem,
    YoutubeQuotaItem,
    YoutubeSearchCacheItem,
    YoutubeVideoCacheItem,
)
from shared.schemas.places import GeoPoint
from shared.schemas.youtube import VideoMeta

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

DAY_SEC = 86_400


class CoordCacheRepo:
    def __init__(self, resource: "DynamoDBServiceResource", table_name: str) -> None:
        self._resource = resource
        self._table: Table = resource.Table(table_name)
        self._table_name = table_name

    def put(self, place_id: str, point: GeoPoint, *, now: int, ttl_days: int) -> None:
        item = CoordCacheItem(
            place_id=place_id, lat=point.lat, lng=point.lng, expires_at=now + ttl_days * DAY_SEC
        )
        self._table.put_item(Item=to_item(item))

    def get_many(self, place_ids: Collection[str], *, now: int) -> dict[str, CoordCacheItem]:
        if not place_ids:
            return {}
        keys = [{"placeId": p} for p in sorted(set(place_ids))]
        items = (
            CoordCacheItem.model_validate(i)
            for i in batch_get(self._resource, self._table_name, keys)
        )
        return {i.place_id: i for i in items if i.expires_at > now}


def search_hash(params: Mapping[str, Any]) -> str:
    """검색 조건 전체(목적지·검색어·정렬·페이지·언어·기간)를 정규화해 해시한다."""
    canonical = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class YoutubeCacheRepo:
    def __init__(self, resource: "DynamoDBServiceResource", table_name: str) -> None:
        self._resource = resource
        self._table: Table = resource.Table(table_name)
        self._table_name = table_name

    def get_search(self, digest: str, *, now: int) -> list[str] | None:
        resp = self._table.get_item(Key={"pk": f"SEARCH#{digest}", "sk": "RESULT"})
        raw = resp.get("Item")
        if raw is None:
            return None
        item = YoutubeSearchCacheItem.model_validate(from_item(raw))
        return list(item.video_ids) if item.expires_at > now else None

    def put_search(self, digest: str, video_ids: Sequence[str], *, now: int, ttl_days: int) -> None:
        item = YoutubeSearchCacheItem(
            pk=f"SEARCH#{digest}", video_ids=list(video_ids), expires_at=now + ttl_days * DAY_SEC
        )
        self._table.put_item(Item=to_item(item))

    def get_videos(self, video_ids: Collection[str], *, now: int) -> dict[str, VideoMeta]:
        if not video_ids:
            return {}
        keys = [{"pk": f"VIDEO#{v}", "sk": "META"} for v in sorted(set(video_ids))]
        found: dict[str, VideoMeta] = {}
        for raw in batch_get(self._resource, self._table_name, keys):
            item = YoutubeVideoCacheItem.model_validate(raw)
            if item.expires_at <= now:
                continue
            video_id = item.pk.removeprefix("VIDEO#")
            found[video_id] = VideoMeta(
                video_id=video_id,
                channel_id=item.channel_id,
                title=item.title,
                description=item.description,
                duration_sec=item.duration_sec,
                privacy_status=item.privacy_status,
                published_at=item.published_at,
            )
        return found

    def put_video(self, meta: VideoMeta, *, now: int, ttl_days: int) -> None:
        item = YoutubeVideoCacheItem(
            pk=f"VIDEO#{meta.video_id}",
            channel_id=meta.channel_id,
            title=meta.title,
            description=meta.description,
            duration_sec=meta.duration_sec,
            privacy_status=meta.privacy_status,
            published_at=meta.published_at,
            expires_at=now + ttl_days * DAY_SEC,
        )
        self._table.put_item(Item=to_item(item))

    def take_search_quota(self, day: str, *, limit: int, now: int) -> bool:
        """오늘(UTC) search.list 호출 1회를 쓴다. 상한에 닿았으면 False(캐시만 쓴다)."""
        try:
            resp = self._table.update_item(
                Key={"pk": f"QUOTA#{day}", "sk": "SEARCH"},
                UpdateExpression="ADD #c :one SET expiresAt = :exp",
                ConditionExpression="attribute_not_exists(#c) OR #c < :limit",
                ExpressionAttributeNames={"#c": "count"},
                ExpressionAttributeValues={":one": 1, ":limit": limit, ":exp": now + 2 * DAY_SEC},
                ReturnValues="ALL_NEW",
            )
        except ClientError as e:
            if is_conditional_failure(e):
                return False
            raise
        YoutubeQuotaItem.model_validate(from_item(resp["Attributes"]))
        return True

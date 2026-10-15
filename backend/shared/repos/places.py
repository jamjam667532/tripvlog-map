"""Places 테이블: PLACE 아이템(영상 기반 표기)과 EVID 근거 아이템.

Google 응답 필드는 저장하지 않는다.
"""

from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from shared.repos.dynamo import batch_get, from_item, is_conditional_failure, to_item
from shared.schemas.items import PlaceEvidenceItem, PlaceItem

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

VIDEO_INDEX = "videoId-index"


class PlacesRepo:
    def __init__(self, resource: "DynamoDBServiceResource", table_name: str) -> None:
        self._resource = resource
        self._table: Table = resource.Table(table_name)
        self._table_name = table_name

    def put_place_if_absent(self, item: PlaceItem) -> bool:
        """처음 관찰한 표기를 남긴다. 이미 있으면 덮어쓰지 않는다."""
        try:
            self._table.put_item(
                Item=to_item(item), ConditionExpression="attribute_not_exists(placeId)"
            )
        except ClientError as e:
            if is_conditional_failure(e):
                return False
            raise
        return True

    def put_evidence(self, item: PlaceEvidenceItem) -> None:
        self._table.put_item(Item=to_item(item))

    def evidence_for_video(self, video_id: str, version: str) -> list[PlaceEvidenceItem]:
        """videoId-index로 이 영상의 근거를 읽고 analysisVersion으로 거른다."""
        items: list[PlaceEvidenceItem] = []
        kwargs: dict[str, Any] = {
            "IndexName": VIDEO_INDEX,
            "KeyConditionExpression": "videoId = :v",
            "FilterExpression": "analysisVersion = :ver",
            "ExpressionAttributeValues": {":v": video_id, ":ver": version},
        }
        while True:
            resp = self._table.query(**kwargs)
            items.extend(PlaceEvidenceItem.model_validate(from_item(i)) for i in resp["Items"])
            last = resp.get("LastEvaluatedKey")
            if not last:
                return items
            kwargs["ExclusiveStartKey"] = last

    def delete_evidence_for_video(self, video_id: str, version: str) -> int:
        """재분석 전에 같은 버전의 이전 근거를 지운다(남은 근거가 섞이지 않게)."""
        old = self.evidence_for_video(video_id, version)
        with self._table.batch_writer() as batch:
            for e in old:
                batch.delete_item(Key={"placeId": e.place_id, "sk": e.sk})
        return len(old)

    def get_places(self, place_ids: Collection[str]) -> dict[str, PlaceItem]:
        if not place_ids:
            return {}
        keys = [{"placeId": p, "sk": "PLACE"} for p in sorted(set(place_ids))]
        items = (
            PlaceItem.model_validate(i) for i in batch_get(self._resource, self._table_name, keys)
        )
        return {i.place_id: i for i in items}

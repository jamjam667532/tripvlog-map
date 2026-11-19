"""[M8] Users 테이블 (spec §4.4, 결정 0010). 사용자는 JWT sub로만 정한다(google:<sub>).

사용자가 확인한 선호(preferences)와 유튜브에서 온 후보(youtube)를 나눠 둔다.
연결 해제·만료 때는 youtube 속성만 지운다.
"""

from typing import TYPE_CHECKING

from shared.repos.dynamo import from_item, to_item
from shared.schemas.items import UserItem

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


class UsersRepo:
    def __init__(self, table: "Table") -> None:
        self._table = table

    def get(self, user_id: str) -> UserItem | None:
        raw = self._table.get_item(Key={"userId": user_id}).get("Item")
        return None if raw is None else UserItem.model_validate(from_item(raw))

    def get_or_new(self, user_id: str) -> UserItem:
        return self.get(user_id) or UserItem(user_id=user_id)

    def put(self, user: UserItem) -> None:
        self._table.put_item(Item=to_item(user))

    def remove_youtube(self, user_id: str) -> None:
        self._table.update_item(Key={"userId": user_id}, UpdateExpression="REMOVE youtube")

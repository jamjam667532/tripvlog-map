"""Google Places Text Search 결과 (spec §5.4).

매칭에 필요한 최소 필드만 둔다. 메모리에서만 쓰고 로그·S3·DynamoDB에 남기지 않는다.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.common import NonEmptyStr


class GeoPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]


class PlaceHit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    place_id: NonEmptyStr
    name: str
    address: str = ""
    location: GeoPoint

    def __repr__(self) -> str:
        # Places 원문·좌표가 로그에 찍히지 않게 ID만 보여준다
        return f"PlaceHit(place_id={self.place_id!r})"

    __str__ = __repr__

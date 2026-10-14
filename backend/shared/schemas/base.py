"""스키마 공통 베이스.

- CamelModel: API 요청·응답, DynamoDB 아이템, 결과 JSON. JSON 키는 camelCase.
- AIModel: Gemini·Bedrock 출력. JSON 키는 명세대로 snake_case, 모르는 키는 무시한다.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class AIModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

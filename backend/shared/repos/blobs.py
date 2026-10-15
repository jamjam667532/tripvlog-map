"""S3 JSON 저장소. 관찰·해석·매칭 요약(analysis/)과 결과(results/)를 모델로 쓰고 읽는다."""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from shared.schemas.base import CamelModel

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

AnalysisPart = Literal["observation", "interpretation", "match"]


def analysis_key(video_id: str, version: str, part: AnalysisPart) -> str:
    return f"analysis/{video_id}/{version}/{part}.json"


def result_key(job_id: str) -> str:
    return f"results/{job_id}/result.json"


class BlobStore:
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self._s3 = client
        self._bucket = bucket

    def put_model(self, key: str, model: BaseModel) -> str:
        # AI 출력(AIModel)은 명세대로 snake_case, 나머지는 camelCase
        body = model.model_dump_json(by_alias=isinstance(model, CamelModel))
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body.encode(),
            ContentType="application/json",
        )
        return key

    def get_model[M: BaseModel](self, key: str, model: type[M]) -> M:
        body = self._s3.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        return model.model_validate_json(body)

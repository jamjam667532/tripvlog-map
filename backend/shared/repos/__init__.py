"""DynamoDB·S3 저장소. 핸들러는 여기와 clients·rules를 조합만 한다."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import boto3

from shared.repos.blobs import BlobStore, analysis_key, result_key
from shared.repos.caches import CoordCacheRepo, YoutubeCacheRepo, search_hash
from shared.repos.jobs import JobNotFound, JobsRepo, with_metrics, with_ref_state, with_refs
from shared.repos.places import PlacesRepo
from shared.repos.video_analysis import LeaseLost, VideoAnalysisRepo
from shared.settings import Settings

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource
    from mypy_boto3_s3.client import S3Client

__all__ = [
    "BlobStore",
    "CoordCacheRepo",
    "JobNotFound",
    "JobsRepo",
    "LeaseLost",
    "PlacesRepo",
    "Repos",
    "VideoAnalysisRepo",
    "YoutubeCacheRepo",
    "analysis_key",
    "result_key",
    "search_hash",
    "with_metrics",
    "with_ref_state",
    "with_refs",
]


@dataclass(frozen=True)
class Repos:
    jobs: JobsRepo
    video_analysis: VideoAnalysisRepo
    places: PlacesRepo
    coords: CoordCacheRepo
    youtube_cache: YoutubeCacheRepo
    blobs: BlobStore

    @classmethod
    def from_settings(
        cls,
        s: Settings,
        *,
        dynamodb: "DynamoDBServiceResource | None" = None,
        s3: "S3Client | None" = None,
    ) -> "Repos":
        if dynamodb is None:
            kwargs: dict[str, Any] = {}
            if s.dynamodb_endpoint:
                kwargs["endpoint_url"] = s.dynamodb_endpoint
            dynamodb = boto3.resource("dynamodb", **kwargs)
        if s3 is None:
            s3 = boto3.client("s3")
        return cls(
            jobs=JobsRepo(dynamodb.Table(s.jobs_table)),
            video_analysis=VideoAnalysisRepo(dynamodb, s.video_analysis_table),
            places=PlacesRepo(dynamodb, s.places_table),
            coords=CoordCacheRepo(dynamodb, s.coord_cache_table),
            youtube_cache=YoutubeCacheRepo(dynamodb, s.youtube_cache_table),
            blobs=BlobStore(s3, s.bucket),
        )

"""VideoAnalysis 테이블. 같은 영상을 여러 작업이 동시에 분석하지 않도록 조건부 쓰기로 선점한다.

선점 규칙 (spec §4.2):
- 아이템 없음 → ANALYZING으로 만들고 분석 (ANALYZE)
- DONE → 재사용 (REUSE)
- ANALYZING이고 leaseUntil > now → 대기 (WAIT)
- ANALYZING이고 leaseUntil <= now, 또는 FAILED → 선점 회수 후 재분석 (ANALYZE)
같은 작업이 다시 선점하면(재시도) 그대로 ANALYZE.
"""

from collections.abc import Callable, Collection
from datetime import datetime
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from shared.repos.dynamo import batch_get, from_item, is_conditional_failure, to_item
from shared.schemas.events import ClaimDecision
from shared.schemas.items import AnalysisUsage, VideoAnalysisItem

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

MAX_CLAIM_ROUNDS = 3


class LeaseLost(Exception):
    """다른 작업이 선점을 가져갔다. 이 작업의 분석 결과는 쓰지 않는다."""


class VideoAnalysisRepo:
    def __init__(self, resource: "DynamoDBServiceResource", table_name: str) -> None:
        self._resource = resource
        self._table: Table = resource.Table(table_name)
        self._table_name = table_name

    def get(self, video_id: str, version: str) -> VideoAnalysisItem | None:
        resp = self._table.get_item(
            Key={"videoId": video_id, "analysisVersion": version}, ConsistentRead=True
        )
        item = resp.get("Item")
        return None if item is None else VideoAnalysisItem.model_validate(from_item(item))

    def claim(
        self,
        video_id: str,
        version: str,
        *,
        channel_id: str,
        job_id: str,
        now: int,
        lease_sec: int,
    ) -> ClaimDecision:
        item = VideoAnalysisItem(
            video_id=video_id,
            analysis_version=version,
            status="ANALYZING",
            lock_owner=job_id,
            lease_until=now + lease_sec,
            channel_id=channel_id,
        )
        for _ in range(MAX_CLAIM_ROUNDS):
            try:
                self._table.put_item(
                    Item=to_item(item),
                    ConditionExpression=(
                        "attribute_not_exists(videoId) OR #s = :failed"
                        " OR (#s = :analyzing AND (leaseUntil <= :now OR lockOwner = :job))"
                    ),
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={
                        ":failed": "FAILED",
                        ":analyzing": "ANALYZING",
                        ":now": now,
                        ":job": job_id,
                    },
                )
                return "ANALYZE"
            except ClientError as e:
                if not is_conditional_failure(e):
                    raise
            existing = self.get(video_id, version)
            if existing is None:
                continue  # 그 사이 지워졌다 → 다시 시도
            if existing.status == "DONE":
                return "REUSE"
            if existing.status == "ANALYZING":
                return "WAIT"
        return "WAIT"

    def _update_owned(
        self,
        video_id: str,
        version: str,
        job_id: str,
        change: Callable[[VideoAnalysisItem], VideoAnalysisItem],
    ) -> VideoAnalysisItem:
        current = self.get(video_id, version)
        if current is None or current.status != "ANALYZING" or current.lock_owner != job_id:
            raise LeaseLost(video_id)
        updated = VideoAnalysisItem.model_validate(change(current).model_dump())
        try:
            self._table.put_item(
                Item=to_item(updated),
                ConditionExpression="#s = :analyzing AND lockOwner = :job",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":analyzing": "ANALYZING", ":job": job_id},
            )
        except ClientError as e:
            if is_conditional_failure(e):
                raise LeaseLost(video_id) from None
            raise
        return updated

    def record_step(
        self,
        video_id: str,
        version: str,
        *,
        job_id: str,
        now: int,
        lease_sec: int,
        observation_s3_key: str | None = None,
        interpretation_s3_key: str | None = None,
        gemini_tokens: int = 0,
        bedrock_input_tokens: int = 0,
        bedrock_output_tokens: int = 0,
    ) -> VideoAnalysisItem:
        """단계 결과(S3 키·사용량)를 기록하고 선점 기한을 늘린다."""

        def change(item: VideoAnalysisItem) -> VideoAnalysisItem:
            usage = AnalysisUsage(
                gemini_tokens=item.usage.gemini_tokens + gemini_tokens,
                bedrock_input_tokens=item.usage.bedrock_input_tokens + bedrock_input_tokens,
                bedrock_output_tokens=item.usage.bedrock_output_tokens + bedrock_output_tokens,
            )
            update: dict[str, object] = {"lease_until": now + lease_sec, "usage": usage}
            if observation_s3_key is not None:
                update["observation_s3_key"] = observation_s3_key
            if interpretation_s3_key is not None:
                update["interpretation_s3_key"] = interpretation_s3_key
            return item.model_copy(update=update)

        return self._update_owned(video_id, version, job_id, change)

    def mark_done(
        self, video_id: str, version: str, *, job_id: str, now: datetime
    ) -> VideoAnalysisItem:
        return self._update_owned(
            video_id,
            version,
            job_id,
            lambda item: item.model_copy(
                update={
                    "status": "DONE",
                    "lock_owner": None,
                    "lease_until": None,
                    "analyzed_at": now,
                    "last_checked_at": now,
                }
            ),
        )

    def mark_failed(self, video_id: str, version: str, *, job_id: str) -> bool:
        """이 작업이 선점한 경우에만 FAILED로 둔다. 다른 작업이 분석 중이면 건드리지 않는다."""
        try:
            self._update_owned(
                video_id,
                version,
                job_id,
                lambda item: item.model_copy(
                    update={"status": "FAILED", "lock_owner": None, "lease_until": None}
                ),
            )
        except LeaseLost:
            return False
        return True

    def done_video_ids(self, video_ids: Collection[str], version: str) -> set[str]:
        """이미 분석이 끝난(DONE) 영상. 예비 영상 대체 선택에 쓴다(결정 0002-5)."""
        if not video_ids:
            return set()
        keys = [{"videoId": v, "analysisVersion": version} for v in sorted(set(video_ids))]
        items = [
            VideoAnalysisItem.model_validate(i)
            for i in batch_get(self._resource, self._table_name, keys)
        ]
        return {i.video_id for i in items if i.status == "DONE"}

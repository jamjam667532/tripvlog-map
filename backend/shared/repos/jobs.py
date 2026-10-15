"""Jobs 테이블. 여러 단계가 같은 작업 아이템을 고치므로 updatedAt 조건으로 낙관적 잠금을 건다."""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from shared.repos.dynamo import from_item, is_conditional_failure, to_item
from shared.schemas.api import Progress, VideoState
from shared.schemas.items import JobItem, JobMetrics, VideoRef

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

MAX_MUTATE_ATTEMPTS = 8


class JobNotFound(Exception):
    pass


def progress_of(refs: Sequence[VideoRef]) -> Progress:
    return Progress(
        total=len(refs),
        analyzed=sum(r.state == "DONE" for r in refs),
        failed=sum(r.state == "FAILED" for r in refs),
    )


def with_refs(job: JobItem, refs: Sequence[VideoRef]) -> JobItem:
    """videoRefs를 바꾸고 progress를 다시 센다."""
    return job.model_copy(update={"video_refs": list(refs), "progress": progress_of(refs)})


def with_ref_state(
    job: JobItem, video_id: str, state: VideoState, *, error: str | None = None
) -> JobItem:
    refs = [
        r.model_copy(update={"state": state, "error": error}) if r.video_id == video_id else r
        for r in job.video_refs
    ]
    return with_refs(job, refs)


def with_metrics(job: JobItem, **deltas: int) -> JobItem:
    """metrics 값에 더한다. 예: with_metrics(job, gemini_tokens=1000)."""
    current = job.metrics.model_dump(by_alias=False)
    for key, delta in deltas.items():
        current[key] = current[key] + delta
    return job.model_copy(update={"metrics": JobMetrics.model_validate(current)})


class JobsRepo:
    def __init__(self, table: "Table") -> None:
        self._table = table

    def create(self, job: JobItem) -> bool:
        """새 작업을 쓴다. 같은 jobId가 이미 있으면 False."""
        try:
            self._table.put_item(
                Item=to_item(job), ConditionExpression="attribute_not_exists(jobId)"
            )
        except ClientError as e:
            if is_conditional_failure(e):
                return False
            raise
        return True

    def get(self, job_id: str) -> JobItem | None:
        resp = self._table.get_item(Key={"jobId": job_id}, ConsistentRead=True)
        item = resp.get("Item")
        return None if item is None else JobItem.model_validate(from_item(item))

    def require(self, job_id: str) -> JobItem:
        job = self.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def find_by_request_id(self, request_id: str) -> str | None:
        """requestId-index(KEYS_ONLY)로 jobId를 찾는다. GSI는 최종 일관성이다."""
        resp = self._table.query(
            IndexName="requestId-index",
            KeyConditionExpression="requestId = :r",
            ExpressionAttributeValues={":r": request_id},
            Limit=1,
        )
        items = resp.get("Items", [])
        return str(items[0]["jobId"]) if items else None

    def mutate(self, job_id: str, change: Callable[[JobItem], JobItem], now: datetime) -> JobItem:
        """읽고 → 고치고 → updatedAt이 그대로일 때만 쓴다. 충돌하면 다시 읽어 재시도."""
        for _ in range(MAX_MUTATE_ATTEMPTS):
            job = self.require(job_id)
            # updatedAt은 반드시 늘어나야 조건이 의미가 있다
            stamp = max(now, job.updated_at + timedelta(microseconds=1))
            updated = change(job).model_copy(update={"updated_at": stamp})
            updated = JobItem.model_validate(updated.model_dump())  # 모델 검증을 다시 거친다
            try:
                self._table.put_item(
                    Item=to_item(updated),
                    ConditionExpression="updatedAt = :prev",
                    ExpressionAttributeValues={":prev": _iso(job)},
                )
            except ClientError as e:
                if is_conditional_failure(e):
                    continue
                raise
            return updated
        raise RuntimeError(f"job {job_id} update conflicted {MAX_MUTATE_ATTEMPTS} times")


def _iso(job: JobItem) -> Any:
    return to_item(job)["updatedAt"]

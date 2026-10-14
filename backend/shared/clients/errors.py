"""외부 API 오류. 메시지에 키·토큰·응답 원문을 넣지 않는다."""


class ExternalApiError(Exception):
    def __init__(self, service: str, status: int | None, reason: str = "") -> None:
        self.service = service
        self.status = status
        super().__init__(f"{service} request failed (status={status}) {reason}".rstrip())


class InvalidModelOutput(Exception):
    """AI 출력이 스키마 검증을 재요청 후에도 통과하지 못함 → 그 영상은 FAILED."""

    def __init__(self, service: str, attempts: int) -> None:
        self.service = service
        self.attempts = attempts
        super().__init__(f"{service} output failed validation after {attempts} attempts")

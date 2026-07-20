from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TransformStatus(Enum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    NOT_FOUND = "not_found"
    INVALID = "invalid"


@dataclass
class TransformResult:
    status: TransformStatus
    job_id: Optional[str] = None
    message: str = ""
    errors: list = field(default_factory=list)

    @classmethod
    def success(cls, job_id: str, message: str = "Job dispatched") -> "TransformResult":
        return cls(status=TransformStatus.SUCCESS, job_id=job_id, message=message)

    @classmethod
    def duplicate(cls, job_id: str) -> "TransformResult":
        return cls(
            status=TransformStatus.DUPLICATE,
            job_id=job_id,
            message="Duplicate submission — existing job returned",
        )

    @classmethod
    def not_found(cls, message: str) -> "TransformResult":
        return cls(status=TransformStatus.NOT_FOUND, message=message)

    @classmethod
    def invalid(cls, message: str) -> "TransformResult":
        return cls(status=TransformStatus.INVALID, message=message)

    @property
    def is_success(self) -> bool:
        return self.status == TransformStatus.SUCCESS

    @property
    def is_duplicate(self) -> bool:
        return self.status == TransformStatus.DUPLICATE

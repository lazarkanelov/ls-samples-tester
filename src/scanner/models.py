"""Scanner data models."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from scanner.config import CloudProvider, IaCType


class DeployStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"
    UNSUPPORTED = "UNSUPPORTED"


_MAX_LOG_BYTES = 10 * 1024  # 10 KB per stream


def _truncate_log(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= _MAX_LOG_BYTES:
        return text
    truncated = encoded[:_MAX_LOG_BYTES].decode("utf-8", errors="replace")
    return truncated + "\n... [truncated]"


@dataclass
class Sample:
    """A discovered sample application."""

    name: str
    org: str
    url: str
    iac_type: IaCType
    cloud_provider: CloudProvider
    description: str
    topics: list[str]
    language: str
    default_branch: str
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "org": self.org,
            "url": self.url,
            "iac_type": self.iac_type.value,
            "cloud_provider": self.cloud_provider.value,
            "description": self.description,
            "topics": self.topics,
            "language": self.language,
            "default_branch": self.default_branch,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Sample:
        updated_at = data["updated_at"]
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        return cls(
            name=data["name"],
            org=data["org"],
            url=data["url"],
            iac_type=IaCType(data["iac_type"]),
            cloud_provider=CloudProvider(data["cloud_provider"]),
            description=data.get("description", ""),
            topics=data.get("topics", []),
            language=data.get("language", ""),
            default_branch=data.get("default_branch", "main"),
            updated_at=updated_at,
        )


@dataclass
class DeployResult:
    """Result of deploying a single sample."""

    sample_name: str
    org: str
    status: DeployStatus
    duration: float
    stdout: str
    stderr: str
    error_message: str | None
    services_used: list[str]
    deployer_command: str
    iac_type: IaCType = IaCType.UNKNOWN
    cloud_provider: CloudProvider = CloudProvider.AWS

    def __post_init__(self) -> None:
        self.stdout = _truncate_log(self.stdout)
        self.stderr = _truncate_log(self.stderr)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_name": self.sample_name,
            "org": self.org,
            "status": self.status.value,
            "duration": self.duration,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_message": self.error_message,
            "services_used": self.services_used,
            "deployer_command": self.deployer_command,
            "iac_type": self.iac_type.value,
            "cloud_provider": self.cloud_provider.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeployResult:
        return cls(
            sample_name=data["sample_name"],
            org=data["org"],
            status=DeployStatus(data["status"]),
            duration=data["duration"],
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            error_message=data.get("error_message"),
            services_used=data.get("services_used", []),
            deployer_command=data.get("deployer_command", ""),
            iac_type=IaCType(data.get("iac_type", "UNKNOWN")),
            cloud_provider=CloudProvider(data.get("cloud_provider", "AWS")),
        )


@dataclass
class ScanReport:
    """Complete scan report for one run."""

    results: list[DeployResult]
    scan_date: str
    total_samples: int
    tool_versions: dict[str, str] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.status == DeployStatus.SUCCESS)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results if r.status == DeployStatus.FAILURE)

    @property
    def timeout_count(self) -> int:
        return sum(1 for r in self.results if r.status == DeployStatus.TIMEOUT)

    @property
    def unsupported_count(self) -> int:
        return sum(1 for r in self.results if r.status == DeployStatus.UNSUPPORTED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.status == DeployStatus.SKIPPED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_date": self.scan_date,
            "total_samples": self.total_samples,
            "results": [r.to_dict() for r in self.results],
            "tool_versions": self.tool_versions,
            "summary": {
                "success": self.success_count,
                "failure": self.failure_count,
                "timeout": self.timeout_count,
                "unsupported": self.unsupported_count,
                "skipped": self.skipped_count,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScanReport:
        results = [DeployResult.from_dict(r) for r in data.get("results", [])]
        return cls(
            results=results,
            scan_date=data["scan_date"],
            total_samples=data["total_samples"],
            tool_versions=data.get("tool_versions", {}),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> ScanReport:
        return cls.from_dict(json.loads(text))

"""Abstract deployer base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from scanner.models import DeployResult


class Deployer(ABC):
    """Abstract base for IaC deployers."""

    def bootstrap(self, timeout: int = 300) -> tuple[bool, str]:
        """Bootstrap deployer environment (e.g., CDK bootstrap). Returns (True, "") by default."""
        return True, ""

    def detect_services(self, sample_dir: Path) -> list[str]:
        """Detect AWS/Azure services used by the sample. Returns empty list by default."""
        return []

    @abstractmethod
    def prepare(self, sample_dir: Path) -> bool:
        """Install dependencies. Return True on success."""
        ...

    @abstractmethod
    def deploy(self, sample_dir: Path, timeout: int) -> DeployResult:
        """Deploy the sample. Return a DeployResult."""
        ...

    @abstractmethod
    def cleanup(self, sample_dir: Path) -> None:
        """Tear down deployed resources."""
        ...

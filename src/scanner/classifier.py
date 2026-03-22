"""Failure classifier — categorises deploy failures by root cause."""
from __future__ import annotations

import logging

import requests

from scanner.models import DeployResult, DeployStatus, FailureCategory

logger = logging.getLogger(__name__)

# Definitive LocalStack-at-fault patterns (conservative — only unambiguous cases)
_LOCALSTACK_BUG_PATTERNS = [
    "not yet implemented",
    "not implemented",
    "unsupportedoperation",
    "notimplementederror",
    " 501 ",
    "501:",
    "http 501",
]

# Deployer tooling / environment patterns
_DEPLOYER_ERROR_PATTERNS = [
    "prepare() failed",
    "bootstrap failed",
    "timed out after",
    "command not found",
    "no such file",
]

# Sample-specific configuration / authoring patterns
_SAMPLE_ERROR_PATTERNS = [
    "config profile",
    "parametervalue",
    "must have values",
    "resolve-s3",
    "unable to upload artifact",
]


def _match(text: str, patterns: list[str]) -> bool:
    lower = text.lower()
    return any(p in lower for p in patterns)


class FailureClassifier:
    """Classifies deploy failures by root cause.

    Primary signal: pattern matching on deployer stdout/stderr/error_message.
    Supplementary: LocalStack /diagnose endpoint for additional LS-side signals.
    """

    def classify(self, result: DeployResult, ls_endpoint: str) -> FailureCategory | None:
        """Return the failure category, or None for SUCCESS results."""
        if result.status == DeployStatus.SUCCESS:
            return None

        if result.status == DeployStatus.TIMEOUT:
            return FailureCategory.TIMEOUT

        # Collect all available text for pattern matching
        combined = " ".join(
            filter(None, [result.error_message, result.stdout, result.stderr])
        )

        # Primary: pattern match on deployer output
        category = self._classify_text(combined)
        if category is not None:
            return category

        # Supplementary: query LocalStack /diagnose endpoint
        diagnose_text = self._fetch_diagnose(ls_endpoint)
        if diagnose_text:
            category = self._classify_text(diagnose_text)
            if category is not None:
                return category

        return FailureCategory.NOT_CLASSIFIED

    def _classify_text(self, text: str) -> FailureCategory | None:
        if not text:
            return None
        if _match(text, _LOCALSTACK_BUG_PATTERNS):
            return FailureCategory.LOCALSTACK_BUG
        if _match(text, _DEPLOYER_ERROR_PATTERNS):
            return FailureCategory.DEPLOYER_ERROR
        if _match(text, _SAMPLE_ERROR_PATTERNS):
            return FailureCategory.SAMPLE_ERROR
        return None

    def _fetch_diagnose(self, ls_endpoint: str) -> str:
        try:
            resp = requests.get(f"{ls_endpoint}/_localstack/diagnose", timeout=5)
            if resp.status_code == 200:
                return resp.text
        except Exception as exc:
            logger.debug("Could not fetch LocalStack diagnose endpoint: %s", exc)
        return ""

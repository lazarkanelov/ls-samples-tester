"""Failure classifier — categorises deploy failures by root cause."""
from __future__ import annotations

import logging
import re

import requests

from scanner.models import DeployResult, DeployStatus, FailureCategory

logger = logging.getLogger(__name__)

# Regex to strip ANSI escape codes from terminal output
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from *text*."""
    return _ANSI_ESCAPE_RE.sub("", text)


# ---------------------------------------------------------------------------
# Pattern lists — all patterns are matched case-insensitively against the
# lowercased, ANSI-stripped combined output text.
# ---------------------------------------------------------------------------

# Definitive LocalStack-at-fault patterns (conservative — only unambiguous cases)
_LOCALSTACK_BUG_PATTERNS = [
    "not yet implemented",
    "not implemented",
    "unsupportedoperation",
    "notimplementederror",
    " 501 ",
    "501:",
    "http 501",
    "500 internal server error",
    "internalfailure",
]

# Deployer tooling / environment patterns
_DEPLOYER_ERROR_PATTERNS = [
    "prepare() failed",
    "bootstrap failed",
    "timed out after",
    "command not found",
    "no such file",
]

# Terraform missing variable patterns
_MISSING_VARIABLE_PATTERNS = [
    "no value for required variable",
    "input required for variable",
    "required variable",
    "module.*requires variable",
]

# IaC provider setup / download failures
_PROVIDER_ERROR_PATTERNS = [
    "failed to initialize provider",
    "could not load provider",
    "failed to instantiate provider",
    "could not satisfy plugin requirements",
    "provider configuration error",
    "error calling provider.configure",
    "no schema for provider",
    "provider is not available",
]

# Resource type not available or unknown
_RESOURCE_NOT_SUPPORTED_PATTERNS = [
    "resource type not supported",
    "resource type not found",
    "unknownresourcetypeexception",
    "resource type was not found",
    "type not found",
]

# Credential / authentication errors
_AUTH_ERROR_PATTERNS = [
    "authfailure",
    "invalidclienttokenid",
    "expiredtokenexception",
    "no valid credential",
    "could not load credentials",
    "unable to locate credentials",
    "invalid credentials",
    "accessdenied",
    "access denied",
]

# Network / connectivity errors
_NETWORK_ERROR_PATTERNS = [
    "connection refused",
    "connection timed out",
    "dial tcp",
    "could not resolve host",
    "dns resolution failed",
    "network unreachable",
    "unable to connect",
]

# Sample-specific configuration / authoring patterns
_SAMPLE_ERROR_PATTERNS = [
    "config profile",
    "parametervalue",
    "must have values",
    "resolve-s3",
    "unable to upload artifact",
    "missing required argument",
    "provider.*not available",
    "variable.*required",
]


def _match(text: str, patterns: list[str]) -> bool:
    """Check if any pattern matches the lowercased text.

    Patterns containing ``.*`` are treated as regex; all others use
    plain substring containment to avoid special-character escaping issues.
    """
    lower = text.lower()
    for p in patterns:
        if ".*" in p:
            if re.search(p, lower) is not None:
                return True
        elif p in lower:
            return True
    return False


class FailureClassifier:
    """Classifies deploy failures by root cause.

    Primary signal: pattern matching on deployer stdout/stderr/error_message
    (ANSI-stripped). Supplementary: LocalStack /diagnose endpoint.
    """

    def classify(self, result: DeployResult, ls_endpoint: str) -> FailureCategory | None:
        """Return the failure category, or None for SUCCESS results."""
        if result.status == DeployStatus.SUCCESS:
            return None

        if result.status == DeployStatus.TIMEOUT:
            return FailureCategory.TIMEOUT

        # Collect all available text, strip ANSI codes
        combined = _strip_ansi(
            " ".join(filter(None, [result.error_message, result.stdout, result.stderr]))
        )

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
        # Order matters: more specific categories before generic ones
        if _match(text, _LOCALSTACK_BUG_PATTERNS):
            return FailureCategory.LOCALSTACK_BUG
        if _match(text, _DEPLOYER_ERROR_PATTERNS):
            return FailureCategory.DEPLOYER_ERROR
        if _match(text, _MISSING_VARIABLE_PATTERNS):
            return FailureCategory.MISSING_VARIABLE
        if _match(text, _PROVIDER_ERROR_PATTERNS):
            return FailureCategory.PROVIDER_ERROR
        if _match(text, _RESOURCE_NOT_SUPPORTED_PATTERNS):
            return FailureCategory.RESOURCE_NOT_SUPPORTED
        if _match(text, _AUTH_ERROR_PATTERNS):
            return FailureCategory.AUTH_ERROR
        if _match(text, _NETWORK_ERROR_PATTERNS):
            return FailureCategory.NETWORK_ERROR
        if _match(text, _SAMPLE_ERROR_PATTERNS):
            return FailureCategory.SAMPLE_ERROR
        return None

    def _fetch_diagnose(self, ls_endpoint: str) -> str:
        try:
            resp = requests.get(f"{ls_endpoint}/_localstack/diagnose", timeout=5)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException as exc:
            logger.debug("Could not fetch LocalStack diagnose endpoint: %s", exc)
        return ""

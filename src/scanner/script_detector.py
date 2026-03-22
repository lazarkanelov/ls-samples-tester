"""Script detector — finds and runs test scripts in sample repos."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_SCRIPT_ENV = {
    **os.environ,
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "LOCALSTACK_HOSTNAME": "localhost",
    "EDGE_PORT": "4566",
}


@dataclass
class DetectedScript:
    """A test script found in a sample repo."""

    path: str
    script_type: str  # "makefile", "shell", or "python"
    command: list[str]


@dataclass
class ScriptOutcome:
    """Result of running detected test scripts."""

    passed: bool
    summary: str
    details: list[str] = field(default_factory=list)


class ScriptDetector:
    """Detects and runs test scripts in sample repositories."""

    def detect(self, sample_dir: Path) -> list[DetectedScript]:
        """Detect test scripts in the sample directory (priority order).

        Priority: Makefile test target > test*.sh shell scripts > test_*.py Python files.
        Returns a list of DetectedScript objects (at most one per type).
        """
        # Priority 1: Makefile with test target
        makefile = sample_dir / "Makefile"
        if makefile.exists() and self._has_test_target(makefile):
            return [DetectedScript(
                path=str(makefile),
                script_type="makefile",
                command=["make", "test"],
            )]

        # Priority 2: test*.sh shell scripts
        shell_script = self._find_shell_script(sample_dir)
        if shell_script is not None:
            return [DetectedScript(
                path=str(shell_script),
                script_type="shell",
                command=["bash", str(shell_script)],
            )]

        # Priority 3: test_*.py Python test files
        python_test = self._find_python_test(sample_dir)
        if python_test is not None:
            return [DetectedScript(
                path=str(python_test),
                script_type="python",
                command=[sys.executable, str(python_test)],
            )]

        return []

    def run(
        self, sample_dir: Path, scripts: list[DetectedScript], timeout: int = 60
    ) -> ScriptOutcome:
        """Run the first detected script and return the outcome."""
        if not scripts:
            return ScriptOutcome(passed=True, summary="No test scripts found", details=[])

        script = scripts[0]
        try:
            result = subprocess.run(
                script.command,
                cwd=sample_dir,
                capture_output=True,
                text=True,
                env=_SCRIPT_ENV,
                timeout=timeout,
            )
            passed = result.returncode == 0
            details = []
            if result.stdout:
                details.append(f"stdout: {result.stdout[:500]}")
            if result.stderr:
                details.append(f"stderr: {result.stderr[:500]}")
            summary = (
                f"Script {script.path}: {'PASSED' if passed else 'FAILED'} (exit {result.returncode})"
            )
            return ScriptOutcome(passed=passed, summary=summary, details=details)
        except subprocess.TimeoutExpired:
            return ScriptOutcome(
                passed=False,
                summary=f"Script {script.path}: FAILED (timeout after {timeout}s)",
                details=[],
            )
        except Exception as exc:
            return ScriptOutcome(
                passed=False,
                summary=f"Script {script.path}: FAILED ({exc})",
                details=[],
            )

    def _has_test_target(self, makefile: Path) -> bool:
        """Check if a Makefile has a 'test' target."""
        try:
            content = makefile.read_text(errors="replace")
            for line in content.splitlines():
                # A target line starts at column 0 and ends with ':'
                stripped = line.split("#")[0]  # strip inline comments
                if stripped.rstrip().endswith(":"):
                    target = stripped.rstrip().rstrip(":").strip()
                    if target == "test":
                        return True
                # Also handle "test:" at the start of the line
                if stripped.startswith("test:") or stripped.startswith("test "):
                    return True
        except OSError:
            pass
        return False

    def _find_shell_script(self, sample_dir: Path) -> Path | None:
        """Find a test*.sh script in root or scripts/ subdirectory."""
        # Check root dir
        for path in sorted(sample_dir.glob("test*.sh")):
            if path.is_file():
                return path
        # Check scripts/ subdirectory
        scripts_dir = sample_dir / "scripts"
        if scripts_dir.is_dir():
            for path in sorted(scripts_dir.glob("test*.sh")):
                if path.is_file():
                    return path
        return None

    def _find_python_test(self, sample_dir: Path) -> Path | None:
        """Find a test_*.py file in root or tests/ subdirectory."""
        # Check root dir
        for path in sorted(sample_dir.glob("test_*.py")):
            if path.is_file():
                return path
        # Check tests/ subdirectory
        tests_dir = sample_dir / "tests"
        if tests_dir.is_dir():
            for path in sorted(tests_dir.glob("test_*.py")):
                if path.is_file():
                    return path
        return None

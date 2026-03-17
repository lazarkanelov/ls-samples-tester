"""Sandbox — clone and clean up sample repositories."""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from scanner.models import Sample

logger = logging.getLogger(__name__)


class Sandbox:
    """Manages temporary directories for sample clones."""

    def clone_sample(self, sample: Sample) -> Path:
        """Shallow-clone the sample repo into a temp directory and return the path."""
        tmp = Path(tempfile.mkdtemp(prefix=f"scanner-{sample.name}-"))
        logger.debug("Cloning %s into %s", sample.url, tmp)
        subprocess.run(
            ["git", "clone", "--depth", "1", sample.url, str(tmp)],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        return tmp

    def cleanup(self, sample_dir: Path) -> None:
        """Remove the cloned directory."""
        shutil.rmtree(sample_dir, ignore_errors=True)

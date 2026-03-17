"""HTML report generator using Jinja2 templates."""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from scanner.models import ScanReport

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _sanitize_filename(name: str) -> str:
    """Convert a sample name to a safe filename component."""
    return re.sub(r"[^a-zA-Z0-9\-_]", "-", name)


class ReportGenerator:
    """Generates static HTML reports from a ScanReport."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )
        self._env.filters["sanitize_filename"] = _sanitize_filename

    def generate(self, report: ScanReport) -> None:
        """Generate report.html and per-sample detail pages in output_dir."""
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Main summary report
        summary_tmpl = self._env.get_template("report.html")
        html = summary_tmpl.render(report=report)
        (self._output_dir / "report.html").write_text(html, encoding="utf-8")

        # Per-sample detail pages
        detail_tmpl = self._env.get_template("sample_detail.html")
        for result in report.results:
            safe_name = _sanitize_filename(result.sample_name)
            detail_html = detail_tmpl.render(result=result, report=report)
            (self._output_dir / f"{safe_name}-detail.html").write_text(
                detail_html, encoding="utf-8"
            )

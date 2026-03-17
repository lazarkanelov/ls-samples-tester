"""Trend tracking and GitHub Pages index generation."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from scanner.models import ScanReport

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _build_entry(report: ScanReport) -> dict[str, Any]:
    """Build a trends.json entry from a ScanReport."""
    by_iac: dict[str, dict[str, int]] = {}
    by_cloud: dict[str, dict[str, int]] = {}

    for r in report.results:
        iac = r.iac_type.value
        cloud = r.cloud_provider.value
        status = r.status.value.lower()

        by_iac.setdefault(iac, {})
        by_iac[iac][status] = by_iac[iac].get(status, 0) + 1

        by_cloud.setdefault(cloud, {})
        by_cloud[cloud][status] = by_cloud[cloud].get(status, 0) + 1

    return {
        "date": report.scan_date,
        "total": report.total_samples,
        "success": report.success_count,
        "failure": report.failure_count,
        "timeout": report.timeout_count,
        "unsupported": report.unsupported_count,
        "skipped": report.skipped_count,
        "by_iac_type": by_iac,
        "by_cloud": by_cloud,
    }


class TrendTracker:
    """Tracks scan results over time and generates GitHub Pages index."""

    def __init__(self, trends_path: Path) -> None:
        self._path = trends_path

    def _load(self) -> list[dict[str, Any]]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                return []
        return []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(entries, indent=2))

    def update(self, report: ScanReport) -> None:
        """Append or update the entry for report.scan_date (upsert)."""
        entries = self._load()
        new_entry = _build_entry(report)
        # Upsert: replace existing entry for the same date
        for i, entry in enumerate(entries):
            if entry.get("date") == report.scan_date:
                entries[i] = new_entry
                self._save(entries)
                return
        entries.append(new_entry)
        self._save(entries)

    def get_chart_data(self) -> dict[str, Any]:
        """Return trend data formatted for Chart.js."""
        entries = self._load()
        labels = [e["date"] for e in entries]
        success_data = [e.get("success", 0) for e in entries]
        failure_data = [e.get("failure", 0) for e in entries]
        timeout_data = [e.get("timeout", 0) for e in entries]
        return {
            "labels": labels,
            "datasets": [
                {
                    "label": "Success",
                    "data": success_data,
                    "borderColor": "#2e7d32",
                    "backgroundColor": "rgba(46,125,50,0.1)",
                },
                {
                    "label": "Failure",
                    "data": failure_data,
                    "borderColor": "#c62828",
                    "backgroundColor": "rgba(198,40,40,0.1)",
                },
                {
                    "label": "Timeout",
                    "data": timeout_data,
                    "borderColor": "#e65100",
                    "backgroundColor": "rgba(230,81,0,0.1)",
                },
            ],
        }

    def prune_old_reports(self, reports_dir: Path, keep: int) -> None:
        """Remove oldest report directories, keeping only `keep` most recent."""
        dirs = [d for d in reports_dir.iterdir() if d.is_dir()]
        dirs.sort(key=lambda d: d.stat().st_mtime)
        for old in dirs[: max(0, len(dirs) - keep)]:
            import shutil

            shutil.rmtree(old, ignore_errors=True)

    def generate_index(self, output_dir: Path) -> None:
        """Generate index.html for GitHub Pages in output_dir."""
        entries = self._load()
        chart_data = self.get_chart_data()

        # Collect report subdirs (date-named directories)
        report_dirs = sorted(
            [d.name for d in output_dir.iterdir() if d.is_dir()],
            reverse=True,
        ) if output_dir.exists() else []

        latest = entries[-1] if entries else None

        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )
        tmpl = env.get_template("index.html")
        html = tmpl.render(
            entries=entries,
            chart_data=chart_data,
            report_dirs=report_dirs,
            latest=latest,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text(html, encoding="utf-8")

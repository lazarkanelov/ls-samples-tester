"""Trend tracking and GitHub Pages index generation."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from scanner.models import DeployStatus, ScanReport

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _build_entry(report: ScanReport, regressions: list[dict[str, str]] | None = None) -> dict[str, Any]:
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
        "partial": report.partial_count,
        "by_iac_type": by_iac,
        "by_cloud": by_cloud,
        "by_failure_category": report.category_counts,
        "regressions": regressions or [],
    }


def _detect_regressions(results_dir: Path, current_report: ScanReport) -> list[dict[str, str]]:
    """Compare current scan against previous results file to find regressions.

    A regression is a sample that was SUCCESS in the previous run and is now
    FAILURE or PARTIAL.  Returns an empty list when no previous file exists or
    when the previous scan covered fewer than 80 % of the current sample count
    (partial-scan guard).
    """
    if not results_dir.exists():
        return []

    current_date_file = results_dir / f"{current_report.scan_date}.json"
    prev_files = sorted(
        f for f in results_dir.glob("*.json") if f != current_date_file
    )
    if not prev_files:
        return []

    prev_file = prev_files[-1]
    try:
        prev_data = json.loads(prev_file.read_text())
    except Exception:
        return []

    prev_results: list[dict[str, Any]] = prev_data.get("results", [])

    # Partial-scan guard: skip comparison if previous run was much smaller
    current_count = len(current_report.results)
    if current_count > 0 and len(prev_results) < 0.8 * current_count:
        return []

    # Build name → status map from previous file
    prev_map: dict[str, str] = {}
    for r in prev_results:
        name = f"{r.get('org', '')}/{r.get('sample_name', '')}"
        prev_map[name] = str(r.get("status", ""))

    regressions: list[dict[str, str]] = []
    for r in current_report.results:
        name = f"{r.org}/{r.sample_name}"
        prev_status = prev_map.get(name)
        if prev_status == DeployStatus.SUCCESS.value and r.status in (
            DeployStatus.FAILURE,
            DeployStatus.PARTIAL,
        ):
            regressions.append({"name": name, "from": "SUCCESS", "to": r.status.value})

    return regressions


class TrendTracker:
    """Tracks scan results over time and generates GitHub Pages index."""

    def __init__(self, trends_path: Path) -> None:
        self._path = trends_path

    def _load(self) -> list[dict[str, Any]]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())  # type: ignore[return-value]
            except Exception:
                return []
        return []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(entries, indent=2))

    def update(self, report: ScanReport, results_dir: Path | None = None) -> None:
        """Append or update the entry for report.scan_date (upsert)."""
        entries = self._load()
        regressions = _detect_regressions(results_dir, report) if results_dir is not None else []
        new_entry = _build_entry(report, regressions)
        # Upsert: replace existing entry for the same date
        for i, entry in enumerate(entries):
            if entry.get("date") == report.scan_date:
                entries[i] = new_entry
                self._save(entries)
                return
        entries.append(new_entry)
        self._save(entries)

    def get_chart_data(self) -> dict[str, Any]:
        """Return trend data formatted for Chart.js (main pass/fail chart)."""
        entries = self._load()
        labels = [e["date"] for e in entries]
        success_data = [e.get("success", 0) for e in entries]
        failure_data = [e.get("failure", 0) for e in entries]
        timeout_data = [e.get("timeout", 0) for e in entries]
        partial_data = [e.get("partial", 0) for e in entries]
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
                {
                    "label": "Partial",
                    "data": partial_data,
                    "borderColor": "#f9a825",
                    "backgroundColor": "rgba(249,168,37,0.1)",
                },
            ],
        }

    def get_iac_chart_data(self) -> dict[str, Any]:
        """Return per-IaC success counts formatted for Chart.js stacked bar chart."""
        entries = self._load()
        labels = [e["date"] for e in entries]

        iac_types: set[str] = set()
        for e in entries:
            iac_types.update(e.get("by_iac_type", {}).keys())

        # Colour palette for IaC types
        _COLORS = [
            "#1565c0", "#2e7d32", "#c62828", "#e65100",
            "#6a1b9a", "#00695c", "#4e342e", "#37474f",
        ]
        datasets: list[dict[str, Any]] = []
        for i, iac in enumerate(sorted(iac_types)):
            success_vals = [
                e.get("by_iac_type", {}).get(iac, {}).get("success", 0)
                for e in entries
            ]
            datasets.append({
                "label": iac,
                "data": success_vals,
                "backgroundColor": _COLORS[i % len(_COLORS)],
            })

        return {"labels": labels, "datasets": datasets}

    def get_category_chart_data(self) -> dict[str, Any]:
        """Return failure category counts over time formatted for Chart.js."""
        entries = self._load()
        labels = [e["date"] for e in entries]

        categories: set[str] = set()
        for e in entries:
            categories.update(e.get("by_failure_category", {}).keys())

        datasets: list[dict[str, Any]] = []
        for cat in sorted(categories):
            data = [e.get("by_failure_category", {}).get(cat, 0) for e in entries]
            datasets.append({"label": cat, "data": data})

        return {"labels": labels, "datasets": datasets}

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
        iac_chart_data = self.get_iac_chart_data()
        category_chart_data = self.get_category_chart_data()

        # Collect report subdirs (date-named directories)
        report_dirs = sorted(
            [d.name for d in output_dir.iterdir() if d.is_dir()],
            reverse=True,
        ) if output_dir.exists() else []

        latest = entries[-1] if entries else None
        regressions: list[dict[str, str]] = latest.get("regressions", []) if latest else []  # type: ignore[union-attr]

        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )
        tmpl = env.get_template("index.html")
        html = tmpl.render(
            entries=entries,
            chart_data=chart_data,
            iac_chart_data=iac_chart_data,
            category_chart_data=category_chart_data,
            report_dirs=report_dirs,
            latest=latest,
            regressions=regressions,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text(html, encoding="utf-8")

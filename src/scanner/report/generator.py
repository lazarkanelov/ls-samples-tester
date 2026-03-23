"""HTML report generator using Jinja2 templates."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from scanner.models import DeployStatus, ScanReport

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _sanitize_filename(name: str) -> str:
    """Convert a sample name to a safe filename component."""
    return re.sub(r"[^a-zA-Z0-9\-_]", "-", name)


def _compute_service_stats(report: ScanReport) -> dict[str, dict[str, int]]:
    """Aggregate services_used across all results.

    Returns {service: {"total": N, "success": N, "failure": N, "partial": N}},
    sorted by total count descending.
    """
    stats: dict[str, dict[str, int]] = {}
    for r in report.results:
        for svc in r.services_used:
            if svc not in stats:
                stats[svc] = {"total": 0, "success": 0, "failure": 0, "partial": 0}
            stats[svc]["total"] += 1
            if r.status == DeployStatus.SUCCESS:
                stats[svc]["success"] += 1
            elif r.status == DeployStatus.FAILURE:
                stats[svc]["failure"] += 1
            elif r.status == DeployStatus.PARTIAL:
                stats[svc]["partial"] += 1
    return dict(sorted(stats.items(), key=lambda item: (-item[1]["total"], item[0])))


def _compute_service_heatmap(
    report: ScanReport,
) -> tuple[list[str], dict[str, dict[str, int | None]]]:
    """Compute per-service success rates by IaC type.

    Returns (sorted_iac_types, {service: {iac_type: success_pct_or_none}}).
    Only considers results with non-empty services_used.
    """
    iac_types: set[str] = set()
    raw: dict[str, dict[str, dict[str, int]]] = {}

    for r in report.results:
        if not r.services_used:
            continue
        iac = r.iac_type.value
        iac_types.add(iac)
        for svc in r.services_used:
            raw.setdefault(svc, {})
            raw[svc].setdefault(iac, {"total": 0, "success": 0})
            raw[svc][iac]["total"] += 1
            if r.status == DeployStatus.SUCCESS:
                raw[svc][iac]["success"] += 1

    sorted_iac = sorted(iac_types)
    heatmap: dict[str, dict[str, int | None]] = {}
    for svc, iac_data in raw.items():
        heatmap[svc] = {}
        for iac in sorted_iac:
            if iac in iac_data and iac_data[iac]["total"] > 0:
                heatmap[svc][iac] = int(
                    100 * iac_data[iac]["success"] / iac_data[iac]["total"]
                )
            else:
                heatmap[svc][iac] = None

    return sorted_iac, heatmap


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

        # Compute service coverage data (only when any result has services)
        has_service_data = any(r.services_used for r in report.results)
        service_stats: dict[str, Any] = {}
        iac_types: list[str] = []
        service_heatmap: dict[str, dict[str, int | None]] = {}
        if has_service_data:
            service_stats = _compute_service_stats(report)
            iac_types, service_heatmap = _compute_service_heatmap(report)

        # Main summary report
        summary_tmpl = self._env.get_template("report.html")
        html = summary_tmpl.render(
            report=report,
            service_stats=service_stats,
            service_iac_types=iac_types,
            service_heatmap=service_heatmap,
        )
        (self._output_dir / "report.html").write_text(html, encoding="utf-8")

        # Per-sample detail pages
        detail_tmpl = self._env.get_template("sample_detail.html")
        for result in report.results:
            safe_name = _sanitize_filename(result.sample_name)
            detail_html = detail_tmpl.render(result=result, report=report)
            (self._output_dir / f"{safe_name}-detail.html").write_text(
                detail_html, encoding="utf-8"
            )

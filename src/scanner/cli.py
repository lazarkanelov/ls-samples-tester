"""CLI entry point for the LocalStack Sample Tester."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from scanner.config import Config

logger = logging.getLogger(__name__)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """LocalStack Sample Tester — weekly compatibility scanner for AWS/Azure samples."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config()


@cli.command()
@click.option("--org", multiple=True, help="GitHub org(s) to discover (overrides config).")
@click.option("--max-repos-per-org", default=None, type=int, help="Cap repos per org.")
@click.option("--no-cache", is_flag=True, help="Force fresh API queries, bypassing the local cache.")
@click.pass_context
def discover(
    ctx: click.Context,
    org: tuple[str, ...],
    max_repos_per_org: int | None,
    no_cache: bool,
) -> None:
    """Discover sample apps from GitHub orgs and build the registry."""
    from scanner.discovery.etag_cache import ETagCache
    from scanner.discovery.github_client import GitHubClient
    from scanner.discovery.registry import SampleRegistry

    config: Config = ctx.obj["config"]
    if max_repos_per_org is not None:
        config.max_repos_per_org = max_repos_per_org
    orgs = list(org) if org else config.target_orgs

    client = GitHubClient(config=config)
    registry = SampleRegistry(path=config.registry_path)
    cache = None if no_cache else ETagCache(path=config.cache_path, ttl_hours=config.cache_ttl_hours)

    click.echo(f"Discovering IaC samples across {len(orgs)} org(s){'  [cache bypassed]' if no_cache else ''}...")
    samples = client.discover_all(orgs, cache=cache)

    # Persist per org to preserve any orgs not included in this run
    for org_name in orgs:
        org_samples = [s for s in samples if s.org == org_name]
        registry.save_partial(org_name, org_samples)

    click.echo(f"\nTotal samples discovered: {len(samples)}")
    click.echo(f"Registry written to {config.registry_path}")


@cli.command()
@click.option("--limit", default=None, type=int, help="Max samples to scan.")
@click.option("--external-localstack", is_flag=True, help="Use already-running LocalStack.")
@click.option("--localstack-image", default=None, type=str, help="LocalStack Docker image to use (overrides config default).")
@click.pass_context
def scan(ctx: click.Context, limit: int | None, external_localstack: bool, localstack_image: str | None) -> None:
    """Deploy samples against LocalStack and record results."""
    from scanner.discovery.registry import SampleRegistry
    from scanner.priority import sort_samples_by_priority
    from scanner.report.generator import ReportGenerator
    from scanner.report.trends import TrendTracker
    from scanner.runner.localstack import LocalStackManager
    from scanner.runner.orchestrator import ScanOrchestrator, _prune_old_results

    config: Config = ctx.obj["config"]
    if localstack_image is not None:
        config.localstack_image = localstack_image
    registry = SampleRegistry(path=config.registry_path)
    samples = registry.load()

    if not samples:
        click.echo("No samples in registry. Run 'discover' first.", err=True)
        sys.exit(1)

    # Sort by IaC priority BEFORE applying --limit so --limit N returns the
    # N highest-priority samples (Terraform first), not the first N by insertion order.
    samples = sort_samples_by_priority(samples, config.scan_priority)

    if limit is not None:
        samples = samples[:limit]

    click.echo(f"Scanning {len(samples)} samples...")

    ls_manager = LocalStackManager(config=config, external=external_localstack)
    orchestrator = ScanOrchestrator(config=config)

    with ls_manager:
        scan_report = orchestrator.run(samples=samples, ls_manager=ls_manager)

    # Write JSON results
    results_dir = Path(config.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    results_file = results_dir / f"{scan_report.scan_date}.json"
    results_file.write_text(scan_report.to_json())
    _prune_old_results(results_dir, config.data_retention_weeks)

    # Generate HTML report
    report_out = Path(config.reports_dir) / scan_report.scan_date
    ReportGenerator(report_out).generate(scan_report)

    # Update trends + regenerate index
    trends = TrendTracker(Path(config.trends_path))
    trends.update(scan_report)
    trends.generate_index(Path(config.reports_dir))

    click.echo(
        f"\nScan complete: {scan_report.success_count} passed, "
        f"{scan_report.failure_count} failed, "
        f"{scan_report.partial_count} partial, "
        f"{scan_report.timeout_count} timed out, "
        f"{scan_report.unsupported_count} unsupported"
    )
    click.echo(f"Results: {results_file}")
    click.echo(f"Report:  {report_out}/report.html")


@cli.command()
@click.option("--input", "input_path", required=True, help="Path to results JSON file.")
@click.option("--output", "output_dir", required=True, help="Output directory for HTML report.")
@click.pass_context
def report(ctx: click.Context, input_path: str, output_dir: str) -> None:
    """Generate HTML report from a results JSON file."""
    import json

    from scanner.models import ScanReport
    from scanner.report.generator import ReportGenerator

    with open(input_path) as f:
        scan_report = ScanReport.from_dict(json.load(f))

    ReportGenerator(Path(output_dir)).generate(scan_report)
    click.echo(f"Report written to {output_dir}")


@cli.command()
@click.option("--max-repos-per-org", default=500, type=int, show_default=True)
@click.option("--limit", default=None, type=int, help="Max samples to scan.")
@click.option("--external-localstack", is_flag=True, help="Use already-running LocalStack.")
@click.option("--localstack-image", default=None, type=str, help="LocalStack Docker image to use (overrides config default).")
@click.pass_context
def run(
    ctx: click.Context,
    max_repos_per_org: int,
    limit: int | None,
    external_localstack: bool,
    localstack_image: str | None,
) -> None:
    """Run the full pipeline: discover → scan → report."""
    ctx.invoke(discover, org=(), max_repos_per_org=max_repos_per_org)
    ctx.invoke(scan, limit=limit, external_localstack=external_localstack, localstack_image=localstack_image)
    click.echo("\nFull pipeline complete.")

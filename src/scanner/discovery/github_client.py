"""GitHub API client for repository discovery."""
from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from github import Github, GithubException, RateLimitExceededException

from scanner.config import Config, IaCType

if TYPE_CHECKING:
    from scanner.discovery.etag_cache import ETagCache
    from scanner.models import Sample

logger = logging.getLogger(__name__)

# Search query per IaC type.  Uses `extension:` for suffix-based matches (.tf,
# .bicep) and `filename:` for exact marker filenames.
_SEARCH_QUERIES: dict[IaCType, str] = {
    IaCType.TERRAFORM: "extension:tf",
    IaCType.AZURE_BICEP: "extension:bicep",
    IaCType.CDK: "filename:cdk.json",
    IaCType.SAM: "filename:samconfig.toml",
    IaCType.CLOUDFORMATION: "filename:template.yaml",
    IaCType.PULUMI: "filename:Pulumi.yaml",
    IaCType.SERVERLESS: "filename:serverless.yml",
    IaCType.AZURE_ARM: "filename:azuredeploy.json",
}


class GitHubClient:
    """GitHub API client supporting both legacy repo-listing and Code Search discovery."""

    def __init__(self, config: Config) -> None:
        self._config = config
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            logger.warning(
                "No GITHUB_TOKEN set — Code Search limited to 10 results/query and 10 req/min. "
                "Set GITHUB_TOKEN for full discovery."
            )
        self._gh = Github(token, per_page=100)

    # ------------------------------------------------------------------
    # Code Search-based discovery (primary path)
    # ------------------------------------------------------------------

    def search_iac_repos(self, org: str, iac_type: IaCType) -> list[Any]:
        """Return unique, non-archived, non-forked repo objects matching the IaC marker.

        Uses GitHub Code Search API. Adds a 2-second delay after each call to
        respect the 30 req/min authenticated rate limit (separate from REST core).
        """
        query_fragment = _SEARCH_QUERIES.get(iac_type)
        if not query_fragment:
            return []

        query = f"{query_fragment} org:{org}"
        cap = self._config.max_repos_per_org

        seen: dict[str, Any] = {}
        attempts = 0
        max_attempts = 3

        while attempts < max_attempts:
            try:
                results = self._gh.search_code(query)
                for cf in results:
                    repo = cf.repository
                    if repo.archived or repo.fork:
                        continue
                    if repo.full_name not in seen:
                        seen[repo.full_name] = repo
                    if len(seen) >= cap:
                        break
                time.sleep(2)  # respect 30 req/min search rate limit
                break

            except RateLimitExceededException:
                wait = self._wait_for_search_rate_limit()
                logger.warning(
                    "Search rate limit hit for %s/%s, waited %ds, retrying...",
                    org, iac_type.value, wait,
                )
                attempts += 1

            except GithubException as exc:
                logger.error("GitHub search error for %s/%s: %s", org, iac_type.value, exc)
                break

        return list(seen.values())

    def discover_all(self, orgs: list[str], cache: ETagCache | None = None) -> list[Sample]:
        """Discover IaC samples across orgs using Code Search.

        Iterates IaC types in self._config.scan_priority order.  Repos that
        match multiple IaC markers are classified by the first (highest-priority)
        match and deduplicated.  If a fresh cache entry exists for an
        (org, iac_type) pair, the API call is skipped.

        Returns a flat list of Sample objects.
        """
        from scanner.discovery.iac_detector import IaCDetector
        from scanner.models import Sample

        detector = IaCDetector(config=self._config)
        # Global dedup key: full_name → ensures each repo appears at most once
        seen_repos: set[str] = set()
        all_samples: list[Sample] = []

        for org in orgs:
            for iac_type in self._config.scan_priority:
                # Check TTL cache first
                if cache is not None:
                    cached = cache.get(org, iac_type)
                    if cached is not None:
                        logger.debug("Cache hit for %s/%s (%d repos)", org, iac_type.value, len(cached))
                        for sample in cached:
                            if sample.org + "/" + sample.name not in seen_repos:
                                seen_repos.add(sample.org + "/" + sample.name)
                                all_samples.append(sample)
                        continue

                # Cache miss — query the API
                repos = self.search_iac_repos(org, iac_type)
                new_samples: list[Sample] = []

                for repo in repos:
                    full_name = repo.full_name
                    if full_name in seen_repos:
                        continue  # already classified by a higher-priority IaC type
                    seen_repos.add(full_name)

                    cloud = detector.get_cloud_provider(iac_type)
                    topics: list[str] = []
                    try:
                        topics = repo.get_topics()
                    except GithubException as exc:
                        logger.debug("Could not fetch topics for %s: %s", repo.full_name, exc)

                    sample = Sample(
                        name=repo.name,
                        org=org,
                        url=repo.html_url,
                        iac_type=iac_type,
                        cloud_provider=cloud,
                        description=repo.description or "",
                        topics=topics,
                        language=repo.language or "",
                        default_branch=repo.default_branch,
                        updated_at=repo.updated_at,
                    )
                    new_samples.append(sample)
                    all_samples.append(sample)

                if cache is not None:
                    cache.put(org, iac_type, new_samples)

        return all_samples

    # ------------------------------------------------------------------
    # Legacy repo-listing path (fallback / backward compat)
    # ------------------------------------------------------------------

    def list_repos(self, org_name: str) -> list[Any]:
        """[Legacy] Return raw GitHub repo objects for an org, capped at max_repos_per_org.

        Skips archived and forked repos. Sorted by update time (newest first).
        Retries pagination on rate limit — waits for reset then continues.
        """
        results: list[Any] = []
        cap = self._config.max_repos_per_org

        try:
            org = self._gh.get_organization(org_name)
            repos = org.get_repos(sort="updated", direction="desc")
            repo_iter = iter(repos)

            while len(results) < cap:
                try:
                    repo = next(repo_iter)
                except StopIteration:
                    break
                except RateLimitExceededException:
                    wait = self._wait_for_rate_limit()
                    logger.warning(
                        "Rate limit hit for %s, waited %ds, resuming pagination...",
                        org_name,
                        wait,
                    )
                    continue  # retry next() after the reset

                if repo.archived or repo.fork:
                    continue
                results.append(repo)

        except GithubException as exc:
            logger.error("GitHub error listing %s: %s", org_name, exc)

        return results

    # ------------------------------------------------------------------
    # Rate limit helpers
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> int:
        """Sleep until the REST core rate limit resets. Returns seconds waited."""
        rate_limit = self._gh.get_rate_limit()
        reset_time = rate_limit.core.reset  # pyright: ignore[reportAttributeAccessIssue]
        now = datetime.now(tz=UTC)
        wait_seconds = max(0, int((reset_time - now).total_seconds())) + 5
        logger.info("REST rate limit reset in %ds, sleeping...", wait_seconds)
        time.sleep(wait_seconds)
        return wait_seconds

    def _wait_for_search_rate_limit(self) -> int:
        """Sleep until the Code Search rate limit resets. Returns seconds waited.

        The search bucket is separate from the core REST bucket:
        - Authenticated: 30 req/min
        - Unauthenticated: 10 req/min
        Uses rate_limit.search.reset (not rate_limit.core.reset).
        """
        rate_limit = self._gh.get_rate_limit()
        reset_time = rate_limit.search.reset  # pyright: ignore[reportAttributeAccessIssue]
        now = datetime.now(tz=UTC)
        wait_seconds = max(0, int((reset_time - now).total_seconds())) + 5
        logger.info("Search rate limit reset in %ds, sleeping...", wait_seconds)
        time.sleep(wait_seconds)
        return wait_seconds

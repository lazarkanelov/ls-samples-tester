"""IaC type detection from GitHub repository file trees."""
from __future__ import annotations

import logging
from typing import Any

from scanner.config import IAC_CLOUD_MAP, CloudProvider, Config, IaCType

logger = logging.getLogger(__name__)

# Detection priority order (first match wins)
_PRIORITY: list[IaCType] = [
    IaCType.CDK,
    IaCType.SAM,
    IaCType.CLOUDFORMATION,
    IaCType.TERRAFORM,
    IaCType.PULUMI,
    IaCType.SERVERLESS,
    IaCType.AZURE_ARM,
    IaCType.AZURE_BICEP,
]


class IaCDetector:
    """Detect IaC type from a GitHub repo file tree (no content reads)."""

    def __init__(self, config: Config) -> None:
        self._config = config

    def detect_from_tree(self, tree: Any) -> IaCType:
        """Return the IaC type by scanning filenames in a git tree."""
        paths = {el.path for el in tree.tree}
        filenames = {p.split("/")[-1] for p in paths}  # basename set
        all_paths = paths  # full paths for suffix checks

        # Build a presence map for quick lookup
        has_cdk_json = "cdk.json" in filenames
        has_template = "template.yaml" in filenames or "template.yml" in filenames
        has_sam_config = (
            "samconfig.toml" in filenames
            or "samconfig.yaml" in filenames
            or any(p.startswith(".aws-sam/") or "/.aws-sam/" in p for p in all_paths)
        )
        has_tf = any(p.endswith(".tf") for p in all_paths)
        has_pulumi = "Pulumi.yaml" in filenames or "Pulumi.yml" in filenames
        has_serverless = "serverless.yml" in filenames or "serverless.yaml" in filenames
        has_azure_arm = "azuredeploy.json" in filenames
        has_azure_bicep = any(p.endswith(".bicep") for p in all_paths)

        # Priority-ordered detection
        if has_cdk_json:
            return IaCType.CDK
        if has_template and has_sam_config:
            return IaCType.SAM
        if has_template or any(p.endswith(".template") for p in all_paths) or "template.json" in filenames:
            return IaCType.CLOUDFORMATION
        if has_tf:
            return IaCType.TERRAFORM
        if has_pulumi:
            return IaCType.PULUMI
        if has_serverless:
            return IaCType.SERVERLESS
        if has_azure_arm:
            return IaCType.AZURE_ARM
        if has_azure_bicep:
            return IaCType.AZURE_BICEP
        return IaCType.UNKNOWN

    def get_cloud_provider(self, iac_type: IaCType) -> CloudProvider:
        return IAC_CLOUD_MAP.get(iac_type, CloudProvider.AWS)

    def detect_batch(self, repos: list[Any], existing: list[Any] | None = None) -> list[Any]:
        """Convert raw GitHub repo objects to Sample objects, skipping UNKNOWN IaC repos.

        Reuses existing Sample entries for repos whose updated_at hasn't changed.
        """
        from scanner.models import Sample

        existing_map = {
            (s.org, s.name): s for s in (existing or [])
        }
        results: list[Any] = []

        for repo in repos:
            try:
                org = repo.full_name.split("/")[0]
                key = (org, repo.name)

                # Reuse existing entry if repo hasn't been updated
                existing_sample = existing_map.get(key)
                if existing_sample and existing_sample.updated_at >= repo.updated_at:
                    results.append(existing_sample)
                    continue

                # Fetch file tree and detect IaC type
                try:
                    tree = repo.get_git_tree(repo.default_branch, recursive=True)
                except Exception:
                    logger.warning("Could not get file tree for %s", repo.full_name)
                    continue

                iac_type = self.detect_from_tree(tree)
                if iac_type == IaCType.UNKNOWN:
                    continue

                cloud = self.get_cloud_provider(iac_type)
                topics: list[str] = []
                try:
                    topics = repo.get_topics()
                except Exception:
                    pass

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
                results.append(sample)

            except Exception as exc:
                logger.warning(
                    "Error processing repo %s: %s",
                    getattr(repo, "full_name", "?"),
                    exc,
                )

        return results

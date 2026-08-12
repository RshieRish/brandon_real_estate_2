"""Archive parser that reports byte-level integrity without semantic records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from services.command_parsers.base import ModuleMetrics, ModuleParseResult
from services.command_provenance import (
    ArchiveArtifactInput,
    ArchiveIntegrityError,
    verify_artifact_bytes,
)


class ArchiveIntegrityParser:
    """Validate every recovered artifact and summarize the archive bundle."""

    module = "archive_integrity"

    def parse(
        self,
        artifacts: Sequence[ArchiveArtifactInput],
        parser_version: str,
    ) -> ModuleParseResult:
        if not isinstance(parser_version, str) or not parser_version.strip():
            raise ArchiveIntegrityError("parser_version must be nonblank")

        materialized = tuple(artifacts)
        seen_paths: set[str] = set()
        seen_hashes: set[str] = set()
        domains: Counter[str] = Counter()
        byte_count = 0
        duplicate_content_count = 0

        for artifact in materialized:
            verify_artifact_bytes(artifact)
            if not isinstance(artifact.domain, str) or not artifact.domain.strip():
                raise ArchiveIntegrityError(
                    f"artifact {artifact.source_path!r} domain must be a "
                    "nonblank string"
                )
            if artifact.source_path in seen_paths:
                raise ArchiveIntegrityError(
                    "archive contains duplicate source_path: "
                    f"{artifact.source_path}"
                )
            seen_paths.add(artifact.source_path)

            if artifact.sha256 in seen_hashes:
                duplicate_content_count += 1
            else:
                seen_hashes.add(artifact.sha256)

            domains[artifact.domain] += 1
            byte_count += artifact.size_bytes

        artifact_count = len(materialized)
        return ModuleParseResult(
            records=(),
            metrics=ModuleMetrics(
                source_system="all",
                module=self.module,
                expected_count=artifact_count,
                observed_count=artifact_count,
                duplicate_content_count=duplicate_content_count,
                details={
                    "artifacts": artifact_count,
                    "bytes": byte_count,
                    "domains": dict(sorted(domains.items())),
                    "duplicate_content": duplicate_content_count,
                },
            ),
        )

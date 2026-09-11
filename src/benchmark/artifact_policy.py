"""Artifact selection policy for benchmark runs.

Determines which output files are written for each parser run.  The policy
is constructed once from CLI arguments and then consulted by every writing
code-path so that the selection is applied consistently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


ALL_ARTIFACTS = (
    "raw.md",
    "document.md",
    "document.enriched.md",
    "document.jsonl",
    "metrics.json",
    "removed_content.jsonl",
    "run.log",
    "native",
)

DEFAULT_ARTIFACTS = (
    "document.md",
    "run.log",
)


class ArtifactSelectionError(
    ValueError
):
    """Invalid artifact-selection request."""


@dataclass(
    frozen=True
)
class ArtifactPolicy:
    """
    Controls which benchmark artifacts are persisted.

    Important:
    this policy controls file writing.

    It does not necessarily disable all internal metric
    calculations. That optimization can be added separately
    after output equivalence has been validated.
    """

    selected: frozenset[str]

    @classmethod
    def from_cli(
        cls,
        values: Iterable[str] | None,
    ) -> "ArtifactPolicy":
        """Build a policy from raw CLI token(s).

        ``None`` produces the default selection (``document.md`` and
        ``run.log``).  The special token ``"all"`` selects every known
        artifact.  Multiple values and comma-separated strings are both
        accepted.

        Args:
            values: Iterable of strings from ``--artifacts``, or ``None``
                to use the default selection.

        Returns:
            A frozen ``ArtifactPolicy`` instance.

        Raises:
            ArtifactSelectionError: If the resulting set would be empty, or
                if any token names an unknown artifact.
        """
        if values is None:
            return cls(
                selected=frozenset(
                    DEFAULT_ARTIFACTS
                )
            )

        normalized: list[str] = []

        for value in values:
            for item in value.split(","):
                item = (
                    item
                    .strip()
                    .lower()
                )

                if item:
                    normalized.append(
                        item
                    )

        if not normalized:
            raise ArtifactSelectionError(
                "At least one artifact must "
                "be selected."
            )

        if "all" in normalized:
            return cls(
                selected=frozenset(
                    ALL_ARTIFACTS
                )
            )

        unknown = sorted(
            set(normalized)
            - set(ALL_ARTIFACTS)
        )

        if unknown:
            allowed = ", ".join(
                (
                    "all",
                    *ALL_ARTIFACTS,
                )
            )

            raise ArtifactSelectionError(
                "Unknown artifact(s): "
                + ", ".join(unknown)
                + ". Allowed values: "
                + allowed
            )

        return cls(
            selected=frozenset(
                normalized
            )
        )

    def includes(
        self,
        artifact: str,
    ) -> bool:
        """Return ``True`` if *artifact* is in the selected set.

        Args:
            artifact: Artifact name, e.g. ``"document.md"``.

        Returns:
            ``True`` when the artifact should be written.
        """
        return (
            artifact
            in self.selected
        )

    def as_list(
        self,
    ) -> list[str]:
        """Return the selected artifacts in canonical ``ALL_ARTIFACTS`` order.

        Returns:
            Ordered list of selected artifact names.
        """
        return [
            artifact
            for artifact
            in ALL_ARTIFACTS
            if artifact
            in self.selected
        ]

    @property
    def is_all(
        self,
    ) -> bool:
        """Return ``True`` when every known artifact is selected."""
        return self.selected == frozenset(
            ALL_ARTIFACTS
        )

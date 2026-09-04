from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


_MARKDOWN_LINK_RE = re.compile(
    r"(?P<prefix>!?\[[^\]]*\]\()(?P<wrapped><)?(?P<target>[^\s)>]+)"
    r"(?P<close>>)?(?P<suffix>(?:\s+(?:\"[^\"]*\"|'[^']*'))?\))"
)
_REMOTE_SCHEMES = frozenset({"http", "https", "data", "mailto"})


@dataclass(frozen=True)
class MarkdownLocalLink:
    target: str
    start: int
    end: int


@dataclass(frozen=True)
class NativeBundleResult:
    markdown: str
    manifest: dict
    relocated_links: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_native_bundle(bundle_root: Path) -> None:
    """Recreate one exact native bundle leaf without touching its siblings."""
    resolved = bundle_root.resolve()
    if resolved == resolved.parent:
        raise ValueError("refusing to clean a filesystem root")
    if bundle_root.exists():
        if not bundle_root.is_dir():
            raise ValueError(f"native bundle root is not a directory: {bundle_root}")
        shutil.rmtree(bundle_root)
    bundle_root.mkdir(parents=True)


def ensure_safe_relative_path(value: str) -> PurePosixPath:
    """Validate a portable bundle path and reject traversal/absolute paths."""
    decoded = unquote(value).replace("\\", "/")
    path = PurePosixPath(decoded)
    if (
        not decoded
        or decoded.startswith("/")
        or re.match(r"^[A-Za-z]:", decoded)
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe relative path: {value!r}")
    return path


def collect_local_markdown_links(markdown: str) -> list[MarkdownLocalLink]:
    links: list[MarkdownLocalLink] = []
    for match in _MARKDOWN_LINK_RE.finditer(markdown):
        target = match.group("target")
        split = urlsplit(target)
        if split.scheme.lower() in _REMOTE_SCHEMES or target.startswith("#"):
            continue
        if split.scheme or split.netloc:
            raise ValueError(f"unsupported local Markdown link: {target!r}")
        ensure_safe_relative_path(split.path)
        links.append(MarkdownLocalLink(target=target, start=match.start("target"), end=match.end("target")))
    return links


def _relative_to_root(
    path: Path,
    root: Path,
) -> Path:
    candidate = path.resolve()
    resolved_root = root.resolve()

    try:
        return candidate.relative_to(
            resolved_root
        )
    except ValueError as exc:
        # Windows may expose the same directory through
        # both its long path and an 8.3 short-name alias.
        # Path.relative_to() compares path components and
        # therefore cannot detect that equivalence.
        for ancestor in (candidate, *candidate.parents):
            try:
                if ancestor.samefile(
                    resolved_root
                ):
                    return candidate.relative_to(
                        ancestor
                    )
            except OSError:
                continue

        raise ValueError(
            f"path escapes source root: {path}"
        ) from exc


def _descendant(
    path: Path,
    root: Path,
) -> Path:
    candidate = path.resolve()

    try:
        _relative_to_root(
            candidate,
            root,
        )
    except ValueError as exc:
        raise ValueError(
            f"asset escapes source root: {path}"
        ) from exc

    return candidate


def relocate_markdown_assets(
    markdown: str,
    *,
    source_markdown_path: Path,
    source_root: Path,
    bundle_root: Path,
) -> tuple[str, list[Path]]:
    """Copy local linked assets to native/assets and rewrite only link targets."""
    links = collect_local_markdown_links(markdown)
    replacements: list[tuple[int, int, str]] = []
    copied: list[Path] = []
    by_source: dict[Path, str] = {}

    for link in links:
        split = urlsplit(link.target)
        relative = ensure_safe_relative_path(split.path)
        source = _descendant(source_markdown_path.parent / Path(*relative.parts), source_root)
        if not source.is_file():
            raise FileNotFoundError(f"Markdown asset not found: {link.target}")

        relocated = by_source.get(source)
        if relocated is None:
            digest = sha256_file(source)
            safe_name = source.name or "asset"
            destination_rel = PurePosixPath("assets") / digest[:16] / safe_name
            destination = bundle_root / Path(*destination_rel.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            relocated = destination_rel.as_posix()
            by_source[source] = relocated
            copied.append(destination)

        suffix = ""
        if split.query:
            suffix += "?" + split.query
        if split.fragment:
            suffix += "#" + split.fragment
        replacements.append((link.start, link.end, relocated + suffix))

    rewritten = markdown
    for start, end, replacement in reversed(replacements):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    return rewritten, copied


def prefix_local_markdown_links(markdown: str, prefix: str) -> str:
    """Prefix local Markdown targets without changing any non-link content."""
    safe_prefix = ensure_safe_relative_path(prefix.rstrip("/")).as_posix() + "/"
    replacements = [
        (link.start, link.end, safe_prefix + link.target)
        for link in collect_local_markdown_links(markdown)
    ]
    rewritten = markdown
    for start, end, replacement in reversed(replacements):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    return rewritten


def write_native_manifest(
    bundle_root: Path,
    *,
    parser: str,
    profile: str,
    bundle_status: str = "available",
) -> dict:
    if bundle_status not in {"available", "unavailable"}:
        raise ValueError(f"invalid native bundle status: {bundle_status}")
    files = []
    if bundle_status == "available":
        for path in sorted(p for p in bundle_root.rglob("*") if p.is_file() and p.name != "manifest.json"):
            files.append({
                "path": path.relative_to(bundle_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    manifest = {
        "schema_version": 1,
        "parser": parser,
        "profile": profile,
        "bundle_status": bundle_status,
        "files": files,
    }
    (bundle_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def copy_native_bundle(
    *,
    source_root: Path,
    source_markdown_path: Path,
    destination: Path,
    parser: str,
    profile: str,
    extra_files: list[Path] | None = None,
) -> NativeBundleResult:
    """Build a self-contained bundle while preserving official Markdown bytes except links."""
    clean_native_bundle(destination)
    markdown = source_markdown_path.read_text(encoding="utf-8")
    rewritten, copied = relocate_markdown_assets(
        markdown,
        source_markdown_path=source_markdown_path,
        source_root=source_root,
        bundle_root=destination,
    )
    markdown_destination = destination / source_markdown_path.name
    markdown_destination.write_text(rewritten, encoding="utf-8")

    seen = {source_markdown_path.resolve()}
    for extra in extra_files or []:
        source = _descendant(extra, source_root)
        if source in seen or not source.is_file():
            continue
        seen.add(source)
        relative_source = _relative_to_root(
            source,
            source_root,
        )

        target = (
            destination
            / "artifacts"
            / relative_source
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    manifest = write_native_manifest(
        destination, parser=parser, profile=profile, bundle_status="available"
    )
    return NativeBundleResult(
        markdown=rewritten,
        manifest=manifest,
        relocated_links=len(copied),
    )

#!/usr/bin/env python3
"""
Utilities for building a prompt/document registry in a single directory.

The registry is populated with symlinks (or copies when symlinks are unavailable)
to markdown sources so downstream code can treat it as a unified prompt catalog
without caring about the original project layout.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, List, Tuple

DEFAULT_REGISTRY_SUBDIR = Path("src") / "prompts" / "_registry"
DEFAULT_SOURCE_DIRECTORIES = (
    Path("src") / "prompts",
    Path("docs"),
)


def _relative_symlink(target: Path, link_path: Path) -> None:
    """
    Create a relative symlink if possible, fall back to copying on platforms
    where symlinks are unavailable.
    """
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    try:
        relative_target = os.path.relpath(target, link_path.parent)
        link_path.symlink_to(relative_target)
    except (OSError, NotImplementedError):
        shutil.copy2(target, link_path)


def _normalise_source_roots(
    project_root: Path,
    sources: Iterable[Path] | None,
) -> List[Tuple[str, Path]]:
    """
    Resolve source directories relative to project root and drop missing entries.
    """
    resolved: List[Tuple[str, Path]] = []
    for raw in sources or []:
        source = raw if raw.is_absolute() else project_root / raw
        try:
            source_resolved = source.resolve()
        except OSError:
            source_resolved = source
        if not source_resolved.exists() or not source_resolved.is_dir():
            continue
        label = source_resolved.name or str(source_resolved).replace(os.sep, "_")
        resolved.append((label, source_resolved))
    return resolved


def parse_source_env(project_root: Path, env_value: str | None) -> List[Tuple[str, Path]]:
    """
    Parse GC_PROMPT_SOURCE_DIRS, returning resolved source directories.
    """
    if env_value:
        entries = [entry.strip() for entry in env_value.split(os.pathsep) if entry.strip()]
        candidates = [Path(entry) for entry in entries]
    else:
        candidates = list(DEFAULT_SOURCE_DIRECTORIES)
    return _normalise_source_roots(project_root, candidates)


def ensure_prompt_registry(
    project_root: Path,
    *,
    registry_dir: Path | None = None,
    source_dirs: Iterable[Tuple[str, Path]] | None = None,
    clean: bool = False,
) -> Path:
    """
    Build or refresh the prompt registry.

    Args:
        project_root: root of the repository/application.
        registry_dir: destination directory for the registry. When None the
                      default `src/prompts/_registry` under the project is used.
        source_dirs: sequence of (label, path) tuples to pull markdown files from.
        clean: when True, the registry directory is wiped before rebuilding.

    Returns:
        Path to the registry directory.
    """
    project_root = project_root.resolve()
    registry = registry_dir or (project_root / DEFAULT_REGISTRY_SUBDIR)
    try:
        registry = registry.resolve()
    except OSError:
        registry = registry

    if clean and registry.exists():
        shutil.rmtree(registry)

    registry.mkdir(parents=True, exist_ok=True)

    sources = list(source_dirs or _normalise_source_roots(project_root, DEFAULT_SOURCE_DIRECTORIES))
    if not sources:
        return registry

    seen: set[Path] = set()
    for label, source_root in sources:
        for path in source_root.rglob("*.md"):
            if not path.is_file():
                continue
            try:
                path_resolved = path.resolve()
            except OSError:
                path_resolved = path
            if path_resolved in seen:
                continue
            seen.add(path_resolved)
            rel = path_resolved.relative_to(source_root)
            destination = registry / label / rel
            _relative_symlink(path_resolved, destination)

    return registry


__all__ = [
    "ensure_prompt_registry",
    "parse_source_env",
    "DEFAULT_REGISTRY_SUBDIR",
]

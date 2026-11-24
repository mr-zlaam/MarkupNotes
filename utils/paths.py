"""Utility functions for standard system paths and file resolution."""

import os
from pathlib import Path
from typing import Iterable, List, Set


def get_default_notes_dir() -> Path:
    """Return the default directory for storing markdown notes.

    Respects the standard Linux ~/Documents/Markup Notes directory.
    Gracefully migrates existing notes from legacy ~/Documents/Notes if present.
    """
    documents_dir = Path.home() / "Documents" / "Markup Notes"
    legacy_notes_dir = Path.home() / "Documents" / "Notes"
    legacy_notetaker_dir = Path.home() / "Documents" / "Note Taker"

    try:
        # Check if legacy directory exists and new directory doesn't exist yet
        if not documents_dir.exists():
            candidate = None
            if legacy_notes_dir.exists() and any(legacy_notes_dir.iterdir()):
                candidate = legacy_notes_dir
            elif legacy_notetaker_dir.exists() and any(legacy_notetaker_dir.iterdir()):
                candidate = legacy_notetaker_dir

            if candidate is not None:
                try:
                    import shutil
                    shutil.copytree(candidate, documents_dir, dirs_exist_ok=True)
                except OSError:
                    pass

        documents_dir.mkdir(parents=True, exist_ok=True)
        return documents_dir
    except OSError:
        # Fallback gracefully if ~/Documents is read-only or in container/sandbox
        fallback = Path.cwd() / "markup_notes"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except OSError:
            return documents_dir


def get_config_dir() -> Path:
    """Return the XDG compliant configuration directory for the application."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        base_dir = Path(xdg_config_home)
    else:
        base_dir = Path.home() / ".config"

    config_dir = base_dir / "markup-notes"
    old_config_dir = base_dir / "note-taker"
    if not config_dir.exists() and old_config_dir.exists():
        try:
            import shutil
            shutil.copytree(old_config_dir, config_dir)
        except OSError:
            pass

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir
    except OSError:
        # Fallback gracefully if ~/.config is read-only (e.g. sandbox, test, or container)
        fallback = Path.home() / "Documents" / "Markup Notes" / ".config"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except OSError:
            return config_dir


def collect_folder_and_descendants(folder: Path, all_folders: Iterable[Path]) -> Set[Path]:
    """Return folder plus all nested descendant folders present in all_folders."""
    result: Set[Path] = {folder}
    for candidate in all_folders:
        if candidate == folder or folder in candidate.parents:
            result.add(candidate)
    return result


def collect_ancestors_in_set(folder: Path, selected: Iterable[Path]) -> Set[Path]:
    """Return any folder in selected that is a strict ancestor of folder."""
    return {candidate for candidate in selected if candidate in folder.parents}


def prune_nested_paths(paths: Iterable[Path]) -> List[Path]:
    """Return deduplicated top-most paths, dropping descendants covered by a selected ancestor."""
    unique_paths: List[Path] = []
    seen: Set[Path] = set()
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
    return [p for p in unique_paths if not any(anc in seen for anc in p.parents)]


def resolve_copy_target_path(target_dir: Path, source_name: str, is_dir: bool) -> Path:
    """Return a non-colliding destination path using 'copy', 'copy1', 'copy2', ... suffixes."""
    candidate = target_dir / source_name
    if not candidate.exists():
        return candidate

    if is_dir:
        stem = source_name
        suffix = ""
    else:
        p = Path(source_name)
        stem = p.stem
        suffix = p.suffix

    first_copy = target_dir / f"{stem} copy{suffix}"
    if not first_copy.exists():
        return first_copy

    counter = 1
    while True:
        numbered = target_dir / f"{stem} copy{counter}{suffix}"
        if not numbered.exists():
            return numbered
        counter += 1


def is_invalid_folder_transfer(src_folder: Path, dst_dir: Path) -> bool:
    """Return True if dst_dir is src_folder itself or a nested descendant of src_folder."""
    try:
        src_res = src_folder.resolve()
        dst_res = dst_dir.resolve()
    except OSError:
        src_res = src_folder
        dst_res = dst_dir
    return dst_res == src_res or src_res in dst_res.parents


def folder_contains_pinned_items(
    folder: Path,
    pinned_notes: Iterable[str],
    pinned_folders: Iterable[str],
    root_dir: Path,
) -> bool:
    """Return True if folder itself is pinned or contains any pinned note or subfolder."""
    try:
        rel_folder = folder.resolve().relative_to(root_dir.resolve()).as_posix()
    except (ValueError, OSError):
        rel_folder = folder.as_posix()

    prefix = f"{rel_folder}/"
    for key in pinned_folders:
        if key == rel_folder or key.startswith(prefix):
            return True
    for key in pinned_notes:
        if key.startswith(prefix):
            return True
    return False

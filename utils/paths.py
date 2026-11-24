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

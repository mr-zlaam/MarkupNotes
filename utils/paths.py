"""Utility functions for standard system paths and file resolution."""

import os
from pathlib import Path
from typing import Any, Iterable, List, Set
from urllib.parse import unquote, urlparse


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


SUPPORTED_DROP_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown", ".mdown", ".mkd", ".txt"})
SUPPORTED_DROP_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"})


def classify_dropped_local_paths(paths: Iterable[Path]) -> tuple[List[Path], List[Path]]:
    """Split dropped local file paths into (markdown_files, image_files)."""
    md_files: List[Path] = []
    img_files: List[Path] = []
    for p in paths:
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        ext = p.suffix.lower()
        if ext in SUPPORTED_DROP_MARKDOWN_EXTENSIONS:
            md_files.append(p)
        elif ext in SUPPORTED_DROP_IMAGE_EXTENSIONS:
            img_files.append(p)
    return md_files, img_files


def extract_local_paths_from_mime(mime_data: Any) -> List[Path]:
    """Extract local file paths from Qt QMimeData, with raw text/uri-list fallback for Wayland."""
    paths: List[Path] = []
    seen: Set[Path] = set()

    if mime_data.hasUrls():
        for url in mime_data.urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p not in seen:
                    seen.add(p)
                    paths.append(p)

    if not paths and mime_data.hasFormat("text/uri-list"):
        try:
            raw = bytes(mime_data.data("text/uri-list")).decode("utf-8", errors="ignore")
        except (TypeError, ValueError):
            raw = ""
        for line in raw.splitlines():
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            if entry.startswith("file://"):
                parsed = urlparse(entry)
                local_str = unquote(parsed.path)
                if local_str:
                    p = Path(local_str)
                    if p not in seen:
                        seen.add(p)
                        paths.append(p)
    return paths


def should_accept_external_file_drag(mime_data: Any, *, allow_images: bool = False) -> bool:
    """Return True if a dragEnter/dragMove event should be accepted for external OS file drops.

    On Wayland, mimeData often advertises text/uri-list before populating URLs until dropEvent,
    so an empty URL list with text/uri-list present must be accepted during drag hover.
    """
    if not (mime_data.hasUrls() or mime_data.hasFormat("text/uri-list")):
        return False
    local_paths = extract_local_paths_from_mime(mime_data)
    if not local_paths:
        return True
    md_files, img_files = classify_dropped_local_paths(local_paths)
    return bool(md_files or (allow_images and img_files))

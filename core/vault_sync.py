"""Portable workspace backup for customizations and settings inside <notes_root>/.markup-notes/."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from core.config import AppSettings

VAULT_META_DIR_NAME = ".markup-notes"
VAULT_CUSTOMIZATIONS_FILENAME = "customizations.json"
VAULT_SETTINGS_FILENAME = "settings.json"


def get_vault_meta_dir(notes_root: Path) -> Path:
    """Return the hidden metadata directory inside the backed-up notes workspace."""
    return notes_root / VAULT_META_DIR_NAME


def get_vault_customizations_path(notes_root: Path) -> Path:
    """Return path to backed-up customizations JSON inside the notes workspace."""
    return get_vault_meta_dir(notes_root) / VAULT_CUSTOMIZATIONS_FILENAME


def get_vault_settings_path(notes_root: Path) -> Path:
    """Return path to backed-up portable settings JSON inside the notes workspace."""
    return get_vault_meta_dir(notes_root) / VAULT_SETTINGS_FILENAME


def file_sha256(path: Path) -> Optional[str]:
    """Return SHA-256 hex digest for `path`, or None if it does not exist."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _normalize_note_color_key(raw_key: str, notes_root: Path) -> str:
    """Convert an absolute note color path under `notes_root` to a portable relative POSIX path."""
    if not raw_key:
        return ""
    candidate = Path(raw_key)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(notes_root.resolve()).as_posix()
        except ValueError:
            return candidate.as_posix()
    return candidate.as_posix()


def _resolve_note_color_key(stored_key: str, notes_root: Path) -> str:
    """Resolve a portable relative note color key back to a local path string."""
    if not stored_key:
        return ""
    candidate = Path(stored_key)
    if candidate.is_absolute():
        return str(candidate)
    return str(notes_root / candidate)


def extract_portable_customizations(settings: "AppSettings", notes_root: Path) -> Dict[str, Any]:
    """Build portable customizations dictionary (colors and pins) for the workspace."""
    normalized_note_colors: Dict[str, str] = {}
    for raw_key, color in settings.appearance.note_colors.items():
        norm = _normalize_note_color_key(raw_key, notes_root)
        if norm and color:
            normalized_note_colors[norm] = str(color)

    return {
        "folder_colors": dict(settings.appearance.folder_colors),
        "note_colors": normalized_note_colors,
        "pinned_notes": list(settings.general.pinned_notes),
        "pinned_folders": list(settings.general.pinned_folders),
    }


def extract_portable_settings(settings: "AppSettings") -> Dict[str, Any]:
    """Build portable app settings dictionary excluding session and credential/remote URL state."""
    data = asdict(settings)
    general = dict(data.get("general", {}))
    general.pop("pinned_notes", None)
    general.pop("pinned_folders", None)

    appearance = {
        "theme": data.get("appearance", {}).get("theme", "dark"),
    }

    bak = dict(data.get("backup", {}))
    bak.pop("github_repo_url", None)

    return {
        "general": general,
        "window": dict(data.get("window", {})),
        "layout": dict(data.get("layout", {})),
        "editor": dict(data.get("editor", {})),
        "markdown": dict(data.get("markdown", {})),
        "appearance": appearance,
        "backup": bak,
    }


def are_local_settings_default(settings: "AppSettings") -> bool:
    """Return True if all portable settings still match factory defaults."""
    from core.config import AppSettings

    return extract_portable_settings(settings) == extract_portable_settings(AppSettings())


def _atomic_write_json_if_changed(path: Path, payload: Dict[str, Any]) -> bool:
    """Write formatted JSON atomically only if content differs from disk."""
    json_text = json.dumps(payload, indent=4, sort_keys=True) + "\n"
    try:
        if path.exists() and path.read_text(encoding="utf-8") == json_text:
            return True
    except (OSError, UnicodeDecodeError):
        pass

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(path.parent),
            encoding="utf-8",
            delete=False,
        ) as tf:
            tf.write(json_text)
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, path)
        return True
    except OSError:
        return False


def export_vault_backup(settings: "AppSettings", notes_root: Path) -> None:
    """Mirror portable customizations and settings into `<notes_root>/.markup-notes/`."""
    _atomic_write_json_if_changed(
        get_vault_customizations_path(notes_root),
        extract_portable_customizations(settings, notes_root),
    )
    _atomic_write_json_if_changed(
        get_vault_settings_path(notes_root),
        extract_portable_settings(settings),
    )


def _read_json_dict(path: Path) -> Optional[Dict[str, Any]]:
    """Read a JSON object safely from disk, returning None on missing or corrupt files."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def read_vault_customizations(notes_root: Path) -> Optional[Dict[str, Any]]:
    """Read backed-up customizations JSON from `<notes_root>/.markup-notes/`."""
    return _read_json_dict(get_vault_customizations_path(notes_root))


def read_vault_settings(notes_root: Path) -> Optional[Dict[str, Any]]:
    """Read backed-up portable settings JSON from `<notes_root>/.markup-notes/`."""
    return _read_json_dict(get_vault_settings_path(notes_root))


def apply_vault_customizations(
    settings: "AppSettings", payload: Dict[str, Any], notes_root: Path
) -> None:
    """Apply backed-up colors and pins into `settings`."""
    raw_folder_colors = payload.get("folder_colors", {})
    if isinstance(raw_folder_colors, dict):
        settings.appearance.folder_colors = {
            str(k): str(v) for k, v in raw_folder_colors.items() if k and v
        }

    raw_note_colors = payload.get("note_colors", {})
    if isinstance(raw_note_colors, dict):
        resolved_note_colors: Dict[str, str] = {}
        for k, v in raw_note_colors.items():
            if k and v:
                resolved_note_colors[_resolve_note_color_key(str(k), notes_root)] = str(v)
        settings.appearance.note_colors = resolved_note_colors

    raw_pinned_notes = payload.get("pinned_notes", [])
    if isinstance(raw_pinned_notes, list):
        settings.general.pinned_notes = [str(p) for p in raw_pinned_notes if isinstance(p, str) and p]

    raw_pinned_folders = payload.get("pinned_folders", [])
    if isinstance(raw_pinned_folders, list):
        settings.general.pinned_folders = [str(p) for p in raw_pinned_folders if isinstance(p, str) and p]


def apply_vault_settings(settings: "AppSettings", payload: Dict[str, Any]) -> "AppSettings":
    """Merge backed-up portable settings into a new `AppSettings` preserving local session/remote URL."""
    from core.config import AppSettings

    merged = asdict(settings)
    for section in ("general", "window", "layout", "editor", "markdown"):
        if isinstance(payload.get(section), dict):
            sec_dict = dict(merged.get(section, {}))
            sec_dict.update(payload[section])
            merged[section] = sec_dict

    if isinstance(payload.get("appearance"), dict) and "theme" in payload["appearance"]:
        app_dict = dict(merged.get("appearance", {}))
        app_dict["theme"] = payload["appearance"]["theme"]
        merged["appearance"] = app_dict

    if isinstance(payload.get("backup"), dict):
        bak_dict = dict(merged.get("backup", {}))
        for key in ("auto_backup", "auto_backup_delay_ms", "backup_interval_min"):
            if key in payload["backup"]:
                bak_dict[key] = payload["backup"][key]
        merged["backup"] = bak_dict

    # Preserve pinned lists from current settings (managed by customizations.json)
    merged["general"]["pinned_notes"] = list(settings.general.pinned_notes)
    merged["general"]["pinned_folders"] = list(settings.general.pinned_folders)
    return AppSettings.from_dict(merged)

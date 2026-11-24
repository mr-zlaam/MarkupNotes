"""Configuration manager with VS Code-style JSON persistence."""

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional

from utils.paths import get_config_dir
from utils.sorting import DEFAULT_SORT_ORDER, VALID_SORT_ORDERS, normalize_sort_order


@dataclass
class WindowConfig:
    width: int = 1050
    height: int = 700
    maximized: bool = False


@dataclass
class LayoutConfig:
    folders_visible: bool = True
    notes_list_visible: bool = True
    folders_width: int = 190
    notes_list_width: int = 280


@dataclass
class GeneralConfig:
    confirm_delete: bool = True
    default_note_name: str = "Untitled Note"
    startup_action: str = "last_note"  # "last_note", "welcome", "empty"
    ui_scale: float = 1.0
    default_sort_order: str = DEFAULT_SORT_ORDER  # "name_asc", "name_desc", "newest", "oldest"


@dataclass
class EditorConfig:
    font_family: str = "System"
    font_size: int = 12
    line_height: float = 1.5
    word_wrap: bool = True
    tab_size: int = 2
    auto_save_delay_ms: int = 400
    horizontal_padding: int = 36


@dataclass
class MarkdownConfig:
    render_latex: bool = True
    render_mermaid: bool = True
    smart_list: bool = True
    code_line_numbers: bool = False


@dataclass
class AppearanceConfig:
    theme: str = "dark"  # "dark", "oled", "system"
    folder_colors: Dict[str, str] = field(default_factory=dict)
    note_colors: Dict[str, str] = field(default_factory=dict)


@dataclass
class BackupConfig:
    auto_backup: bool = False
    auto_backup_delay_ms: int = 2500
    backup_interval_min: int = 15
    github_repo_url: str = ""


@dataclass
class SessionConfig:
    last_folder: str = ""
    last_note: str = ""
    last_cursor_pos: int = 0
    last_scroll_y: int = 0


@dataclass
class AppSettings:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    window: WindowConfig = field(default_factory=WindowConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    editor: EditorConfig = field(default_factory=EditorConfig)
    markdown: MarkdownConfig = field(default_factory=MarkdownConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    session: SessionConfig = field(default_factory=SessionConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppSettings":
        """Instantiate AppSettings with safe fallback defaults for any missing keys."""
        gen_data = data.get("general", {})
        general = GeneralConfig(
            confirm_delete=bool(gen_data.get("confirm_delete", True)),
            default_note_name=str(gen_data.get("default_note_name", "Untitled Note")),
            startup_action=str(gen_data.get("startup_action", "last_note")),
            ui_scale=float(gen_data.get("ui_scale", 1.0)),
            default_sort_order=normalize_sort_order(gen_data.get("default_sort_order")),
        )

        win_data = data.get("window", {})
        win = WindowConfig(
            width=int(win_data.get("width", 1050)),
            height=int(win_data.get("height", 700)),
            maximized=bool(win_data.get("maximized", False)),
        )

        lay_data = data.get("layout", {})
        lay = LayoutConfig(
            folders_visible=bool(lay_data.get("folders_visible", True)),
            notes_list_visible=bool(lay_data.get("notes_list_visible", True)),
            folders_width=int(lay_data.get("folders_width", 190)),
            notes_list_width=int(lay_data.get("notes_list_width", 280)),
        )

        ed_data = data.get("editor", {})
        ed = EditorConfig(
            font_family=str(ed_data.get("font_family", "System")),
            font_size=int(ed_data.get("font_size", 12)),
            line_height=float(ed_data.get("line_height", 1.5)),
            word_wrap=bool(ed_data.get("word_wrap", True)),
            tab_size=int(ed_data.get("tab_size", 2)),
            auto_save_delay_ms=int(ed_data.get("auto_save_delay_ms", 400)),
            horizontal_padding=int(ed_data.get("horizontal_padding", 36)),
        )

        md_data = data.get("markdown", {})
        markdown = MarkdownConfig(
            render_latex=bool(md_data.get("render_latex", True)),
            render_mermaid=bool(md_data.get("render_mermaid", True)),
            smart_list=bool(md_data.get("smart_list", True)),
            code_line_numbers=bool(md_data.get("code_line_numbers", False)),
        )

        app_data = data.get("appearance", {})
        appearance = AppearanceConfig(
            theme=str(app_data.get("theme", "dark")),
            folder_colors=dict(app_data.get("folder_colors", {})),
            note_colors=dict(app_data.get("note_colors", {})),
        )

        bak_data = data.get("backup", {})
        backup = BackupConfig(
            auto_backup=bool(bak_data.get("auto_backup", False)),
            auto_backup_delay_ms=max(
                1000,
                min(600000, int(bak_data.get("auto_backup_delay_ms", 2500))),
            ),
            backup_interval_min=int(bak_data.get("backup_interval_min", 15)),
            github_repo_url=str(bak_data.get("github_repo_url", "")),
        )

        sess_data = data.get("session", {})
        session = SessionConfig(
            last_folder=str(sess_data.get("last_folder", "")),
            last_note=str(sess_data.get("last_note", "")),
            last_cursor_pos=max(0, int(sess_data.get("last_cursor_pos", 0))),
            last_scroll_y=max(0, int(sess_data.get("last_scroll_y", 0))),
        )

        return cls(
            general=general,
            window=win,
            layout=lay,
            editor=ed,
            markdown=markdown,
            appearance=appearance,
            backup=backup,
            session=session,
        )


class ConfigManager:
    """Manages application settings persisted in ~/.config/markup-notes/settings.json."""

    def __init__(self, config_file: Optional[Path] = None) -> None:
        if config_file is not None:
            self.config_path = config_file
        else:
            self.config_path = get_config_dir() / "settings.json"

        self.settings: AppSettings = self.load()

    def load(self) -> AppSettings:
        """Load settings from JSON file, returning defaults if file does not exist or fails."""
        if not self.config_path.exists():
            default_settings = AppSettings()
            self._save_to_disk(default_settings)
            return default_settings

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return AppSettings.from_dict(data)
        except (json.JSONDecodeError, OSError, TypeError):
            # Degrade gracefully on corrupt JSON or read errors
            pass

        return AppSettings()

    def save(self) -> bool:
        """Persist current settings to disk atomically."""
        return self._save_to_disk(self.settings)

    def _save_to_disk(self, settings: AppSettings) -> bool:
        """Atomic file write to prevent configuration corruption."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(settings)
            json_text = json.dumps(data, indent=2)

            # Atomic write via temporary file
            with tempfile.NamedTemporaryFile(
                "w",
                dir=str(self.config_path.parent),
                encoding="utf-8",
                delete=False,
            ) as tf:
                tf.write(json_text)
                tf.flush()
                os.fsync(tf.fileno())
                temp_name = tf.name

            os.replace(temp_name, self.config_path)
            return True
        except OSError:
            return False

    def update_layout(
        self,
        folders_visible: Optional[bool] = None,
        notes_list_visible: Optional[bool] = None,
        folders_width: Optional[int] = None,
        notes_list_width: Optional[int] = None,
    ) -> None:
        """Update and save layout settings."""
        if folders_visible is not None:
            self.settings.layout.folders_visible = folders_visible
        if notes_list_visible is not None:
            self.settings.layout.notes_list_visible = notes_list_visible
        if folders_width is not None and folders_width > 50:
            self.settings.layout.folders_width = folders_width
        if notes_list_width is not None and notes_list_width > 50:
            self.settings.layout.notes_list_width = notes_list_width
        self.save()

    def update_window(self, width: int, height: int, maximized: bool = False) -> None:
        """Update and save window geometry settings."""
        if width > 300 and height > 200:
            self.settings.window.width = width
            self.settings.window.height = height
        self.settings.window.maximized = maximized
        self.save()

    def set_folder_color(self, folder_name: str, color: Optional[str]) -> None:
        """Set or remove custom color for a folder."""
        if color:
            self.settings.appearance.folder_colors[folder_name] = color
        else:
            self.settings.appearance.folder_colors.pop(folder_name, None)
        self.save()

    def get_folder_color(self, folder_name: str) -> Optional[str]:
        """Get custom color for a folder, or None if default."""
        return self.settings.appearance.folder_colors.get(folder_name)

    def set_note_color(self, note_path_str: str, color: Optional[str]) -> None:
        """Set or remove custom color for a note."""
        if color:
            self.settings.appearance.note_colors[note_path_str] = color
        else:
            self.settings.appearance.note_colors.pop(note_path_str, None)
        self.save()

    def get_note_color(self, note_path_str: str) -> Optional[str]:
        """Get custom color for a note, or None if default."""
        return self.settings.appearance.note_colors.get(note_path_str)

    def set_auto_backup(self, enabled: bool) -> None:
        """Update and save automatic backup setting."""
        self.settings.backup.auto_backup = enabled
        self.save()

    def get_auto_backup(self) -> bool:
        """Get automatic backup setting."""
        return self.settings.backup.auto_backup

    def set_auto_backup_delay_ms(self, delay_ms: int) -> None:
        """Update and save automatic backup debounce delay in milliseconds."""
        clamped = max(1000, min(600000, int(delay_ms)))
        self.settings.backup.auto_backup_delay_ms = clamped
        self.save()

    def get_auto_backup_delay_ms(self) -> int:
        """Get clamped automatic backup debounce delay in milliseconds."""
        return max(1000, min(600000, int(self.settings.backup.auto_backup_delay_ms)))

    def update_editor(
        self,
        font_family: Optional[str] = None,
        font_size: Optional[int] = None,
        line_height: Optional[float] = None,
        word_wrap: Optional[bool] = None,
        tab_size: Optional[int] = None,
        auto_save_delay_ms: Optional[int] = None,
        horizontal_padding: Optional[int] = None,
    ) -> None:
        """Update and save editor configuration."""
        if font_family is not None:
            self.settings.editor.font_family = font_family
        if font_size is not None and 10 <= font_size <= 40:
            self.settings.editor.font_size = font_size
        if line_height is not None and 1.0 <= line_height <= 3.0:
            self.settings.editor.line_height = line_height
        if word_wrap is not None:
            self.settings.editor.word_wrap = word_wrap
        if tab_size is not None and tab_size in (2, 4, 8):
            self.settings.editor.tab_size = tab_size
        if auto_save_delay_ms is not None and 100 <= auto_save_delay_ms <= 5000:
            self.settings.editor.auto_save_delay_ms = auto_save_delay_ms
        if horizontal_padding is not None and 8 <= horizontal_padding <= 300:
            self.settings.editor.horizontal_padding = horizontal_padding
        self.save()

    def update_general(
        self,
        confirm_delete: Optional[bool] = None,
        default_note_name: Optional[str] = None,
        startup_action: Optional[str] = None,
        ui_scale: Optional[float] = None,
        default_sort_order: Optional[str] = None,
    ) -> None:
        """Update and save general configuration."""
        if confirm_delete is not None:
            self.settings.general.confirm_delete = confirm_delete
        if default_note_name is not None and default_note_name.strip():
            self.settings.general.default_note_name = default_note_name.strip()
        if startup_action is not None and startup_action in ("last_note", "welcome", "empty"):
            self.settings.general.startup_action = startup_action
        if ui_scale is not None:
            self.settings.general.ui_scale = round(float(ui_scale), 2)
        if default_sort_order is not None and default_sort_order in VALID_SORT_ORDERS:
            self.settings.general.default_sort_order = default_sort_order
        self.save()

    def update_markdown(
        self,
        render_latex: Optional[bool] = None,
        render_mermaid: Optional[bool] = None,
        smart_list: Optional[bool] = None,
        code_line_numbers: Optional[bool] = None,
    ) -> None:
        """Update and save markdown rendering configuration."""
        if render_latex is not None:
            self.settings.markdown.render_latex = render_latex
        if render_mermaid is not None:
            self.settings.markdown.render_mermaid = render_mermaid
        if smart_list is not None:
            self.settings.markdown.smart_list = smart_list
        if code_line_numbers is not None:
            self.settings.markdown.code_line_numbers = code_line_numbers
        self.save()

    def clear_all_custom_colors(self) -> None:
        """Reset all folder and note custom color customizations."""
        self.settings.appearance.folder_colors.clear()
        self.settings.appearance.note_colors.clear()
        self.save()

    def update_session(
        self,
        *,
        last_folder: Optional[str] = None,
        last_note: Optional[str] = None,
        last_cursor_pos: Optional[int] = None,
        last_scroll_y: Optional[int] = None,
        save: bool = True,
    ) -> None:
        """Update and optionally persist last active folder, note, cursor, and scroll state."""
        if last_folder is not None:
            self.settings.session.last_folder = last_folder
        if last_note is not None:
            self.settings.session.last_note = last_note
        if last_cursor_pos is not None:
            self.settings.session.last_cursor_pos = max(0, int(last_cursor_pos))
        if last_scroll_y is not None:
            self.settings.session.last_scroll_y = max(0, int(last_scroll_y))
        if save:
            self.save()

    def reset_to_defaults(self) -> None:
        """Reset all settings to default configuration."""
        self.settings = AppSettings()
        self.save()

"""Editor canvas panel with Obsidian-style cursor-aware Live Preview and debounced auto-save."""

from __future__ import annotations

from datetime import date
import math
from pathlib import Path
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QContextMenuEvent,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QTextBlock,
    QTextBlockFormat,
    QTextCursor,
    QTextOption,
    QTouchEvent,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from core.note import Note
from ui.date_picker import ModernDatePickerDialog
from ui.dialogs import ModernLinkDialog
from ui.find_replace import FindReplaceBar
from ui.highlighter import HR_RE, HTML_KBD_RE, LIST_RE, QUOTE_RE, MarkdownHighlighter
from ui.selection_toolbar import SelectionFormatToolbar
from ui.slash_menu import SlashCommand, SlashCommandPalette
from utils.date_card import render_date_card
from utils.exporter import export_note_to_html, export_note_to_pdf
from utils.video_engine import (
    VideoRegion,
    YouTubeCacheManager,
    get_video_card_dimensions,
    render_video_card,
)
from utils.touch import TouchScrollTracker, is_touch_event
from utils.transient_scrollbar import TransientScrollBarController
from utils.note_io import count_words_fast
from utils.undo_manager import PlainTextUndoManager
from utils.icons import (
    create_backup_icon,
    create_export_icon,
    create_keyboard_icon,
    create_notes_toggle_icon,
    create_open_file_icon,
    create_settings_icon,
    create_sidebar_toggle_icon,
)
from utils.code_engine import (
    CodeRegion,
    get_code_content_width,
    get_code_copy_button_rect,
    get_code_edit_button_rect,
    get_code_gutter_width,
    get_code_scrollbar_geometry,
    render_code_card,
)
from utils.markdown import (
    CHECKBOX_PATTERN,
    apply_highlight_color_to_markdown,
    apply_text_color_to_markdown,
    calculate_block_hanging_indent,
    expand_selection_to_color_tags,
    find_link_at_offset,
    get_auto_continue_prefix,
    get_checkbox_info,
    is_checkbox_line,
    transform_line_block_prefix,
)
from utils.math_engine import (
    INLINE_MATH_RE,
    render_math_to_pixmap,
)
from utils.mermaid_engine import (
    render_mermaid_to_pixmap,
)
from utils.table import (
    TableRegion,
    create_empty_table_row,
    find_next_cell_pos,
    find_prev_cell_pos,
    get_table_column_widths,
    get_table_scrollbar_geometry,
    is_empty_table_row,
    is_table_row,
    is_table_separator,
    render_table,
    split_table_cells,
)


class NoteTitleEdit(QLineEdit):
    """Frameless modern note title input with smooth keyboard navigation (Notion/Craft aesthetic)."""

    down_pressed = pyqtSignal()
    enter_pressed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("NoteTitleEdit")
        self.setPlaceholderText("Untitled")
        title_font = QFont("Cantarell", 22)
        title_font.setPointSize(22)
        title_font.setBold(True)
        self.setFont(title_font)
        self.setStyleSheet("""
            QLineEdit#NoteTitleEdit {
                background-color: transparent;
                border: none;
                color: #ffffff;
                font-size: 26px;
                font-weight: 700;
                padding: 10px 36px 4px 36px;
                selection-background-color: #0a84ff;
            }
            QLineEdit#NoteTitleEdit:focus {
                border: none;
                background-color: transparent;
            }
            QLineEdit#NoteTitleEdit:disabled {
                color: #555555;
            }
        """)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        mods = event.modifiers()
        if bool(mods & Qt.KeyboardModifier.ControlModifier) and not bool(mods & Qt.KeyboardModifier.AltModifier):
            if event.key() in (
                Qt.Key.Key_Comma,
                Qt.Key.Key_Plus,
                Qt.Key.Key_Equal,
                Qt.Key.Key_Minus,
                Qt.Key.Key_Underscore,
                Qt.Key.Key_0,
            ):
                event.ignore()
                return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enter_pressed.emit()
            event.accept()
            return
        elif event.key() == Qt.Key.Key_Down:
            self.down_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MarkdownEditor(QTextEdit):
    """Pure plain-text Markdown editor with cursor-aware Obsidian Live Preview."""

    up_at_top_requested = pyqtSignal()
    find_requested = pyqtSignal(bool)  # is_replace_mode
    find_close_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    zoom_in_requested = pyqtSignal()
    zoom_out_requested = pyqtSignal()
    zoom_reset_requested = pyqtSignal()
    zoom_changed = pyqtSignal(int)
    word_wrap_toggled = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)
        self.setObjectName("MarkdownEditor")
        self.setPlaceholderText("Type text or / for commands")
        self.setAcceptRichText(False)
        self._tab_size: int = 2
        self._horizontal_padding: int = 36
        self._font_size_pt: int = 12
        self._font_family: str = "Cantarell"

        # Guarantee strict Left-to-Right layout and clean word wrapping
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        opt = self.document().defaultTextOption()
        opt.setTextDirection(Qt.LayoutDirection.LeftToRight)
        opt.setAlignment(Qt.AlignmentFlag.AlignLeft)
        opt.setWrapMode(QTextOption.WrapMode.WordWrap)
        self.document().setDefaultTextOption(opt)
        self.setWordWrapMode(QTextOption.WrapMode.WordWrap)

        # Set base editor font in Python so QSyntaxHighlighter can freely scale headings
        base_font = QFont("Cantarell", 16)
        base_font.setPointSize(16)
        self.setFont(base_font)
        self.document().setDefaultFont(base_font)

        # Apply comfortable 120% proportional line height across documents
        cur = self.textCursor()
        bf = cur.blockFormat()
        bf.setLineHeight(120.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cur.setBlockFormat(bf)
        self.setTextCursor(cur)

        # Decouple plain-text Undo/Redo from Qt layout mutations (_update_block_margins)
        self.document().setUndoRedoEnabled(False)
        self.undo_manager = PlainTextUndoManager()
        self._applying_undo_redo: bool = False
        self._resetting_text: bool = False
        self._cleaning_empty_tag: bool = False
        self._pending_text_mutation: bool = False
        self._dirty_margin_blocks: Optional[Set[int]] = None
        self._last_block_count: int = 1

        # Attach cursor-aware Obsidian syntax highlighter
        self.highlighter = MarkdownHighlighter(self.document())
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)
        self.document().contentsChange.connect(self._on_document_contents_change)
        self.document().contentsChanged.connect(self._on_contents_changed)
        self._rendered_block_rects: list[tuple[int, int, QRectF]] = []

        # Horizontal scrolling & interaction states for tables and code blocks
        self._table_scroll_x: dict[int, float] = {}
        self._code_scroll_x: dict[int, float] = {}
        self._scrollbar_drag: Optional[tuple[str, int, float, float, float, float, float]] = None
        self._hovered_copy_btn: Optional[int] = None
        self._hovered_edit_btn: Optional[int] = None
        self._copied_code_block: Optional[int] = None
        self._copied_timer = QTimer(self)
        self._copied_timer.setSingleShot(True)
        self._copied_timer.setInterval(2000)
        self._copied_timer.timeout.connect(self._reset_copied_state)

        # Live markdown rendering toggles
        self.render_latex: bool = True
        self.render_mermaid: bool = True
        self.smart_list: bool = True
        self.code_line_numbers: bool = False

        # Enable mouse and touch tracking
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)

        # Touchscreen gesture tracking & kinetic momentum
        self._touch_tracker = TouchScrollTracker()
        self._last_tap_time: float = 0.0
        self._last_tap_pos: QPointF = QPointF()

        self._kinetic_timer = QTimer(self)
        self._kinetic_timer.setInterval(16)  # ~60 FPS
        self._kinetic_timer.timeout.connect(self._on_kinetic_tick)
        self._kinetic_vx: float = 0.0
        self._kinetic_vy: float = 0.0
        self._kinetic_target: Optional[tuple[str, int, float]] = None

        # Debounced blockquote, list, and checkbox margin updates & atomic batch edit guard
        self._updating_margins: bool = False
        self._margin_timer = QTimer(self)
        self._margin_timer.setSingleShot(True)
        self._margin_timer.setInterval(50)
        self._margin_timer.timeout.connect(self._update_block_margins)

        # Debounced region rescan timer used for large documents (>400 blocks)
        self._region_timer = QTimer(self)
        self._region_timer.setSingleShot(True)
        self._region_timer.setInterval(150)
        self._region_timer.timeout.connect(self._flush_deferred_regions)

        # Slash command palette (Notion-style block creation)
        self.slash_palette = SlashCommandPalette(self)
        self.slash_palette.command_selected.connect(self._on_slash_command_selected)
        self._slash_start_pos: Optional[int] = None

        # Dynamic date card interaction state
        self._date_card_rects: dict[int, tuple[QRectF, date]] = {}
        self._hovered_date_block: Optional[int] = None

        # YouTube video card interaction state
        self._video_card_rects: dict[int, tuple[QRectF, VideoRegion]] = {}
        self._hovered_video_block: Optional[int] = None
        self._hovered_video_play: Optional[int] = None
        YouTubeCacheManager.instance().thumbnail_ready.connect(self._on_youtube_thumbnail_ready)

        # Floating text format bubble toolbar (Notion-style inline formatting)
        self.format_toolbar = SelectionFormatToolbar(self)
        self.format_toolbar.format_requested.connect(self._apply_text_format)
        self.format_toolbar.text_color_requested.connect(self._apply_text_color)
        self.format_toolbar.highlight_color_requested.connect(self._apply_highlight_color)
        self.selectionChanged.connect(self._on_selection_changed)

        # In-note search & replace state
        self._search_matches: list[tuple[int, int]] = []
        self._current_search_idx: int = -1
        self._search_query: str = ""
        self._search_case: bool = False
        self._search_word: bool = False

        # UI Scaling factor (1.0 = default 100%)
        self.ui_scale: float = 1.0

        # Transient auto-hiding scrollbars (vertical & horizontal)
        self._transient_scrollbar = TransientScrollBarController(self.verticalScrollBar(), parent=self)
        self._transient_h_scrollbar = TransientScrollBarController(self.horizontalScrollBar(), parent=self)

    def _on_youtube_thumbnail_ready(self, video_id: str) -> None:
        """Trigger viewport repaint when background YouTube thumbnail/metadata finishes loading."""
        self.viewport().update()

    def set_ui_scale(self, scale: float) -> None:
        """Set UI scale factor and refresh highlighter and viewport."""
        self.ui_scale = float(scale)
        if hasattr(self, "highlighter"):
            self.highlighter.ui_scale = float(scale)
        self._schedule_margin_update(full=True)
        self.viewport().update()

    def _refresh_editor_style(self) -> None:
        """Ensure stylesheet preserves dynamic font size, family, and horizontal padding."""
        pt_size = getattr(self, "_font_size_pt", 12)
        h_pad = getattr(self, "_horizontal_padding", 36)
        fam = getattr(self, "_font_family", "")
        fam_rule = f'font-family: "{fam}";' if fam and fam != "System" else ""
        self.setStyleSheet(f"""
            QTextEdit#MarkdownEditor {{
                font-size: {pt_size}pt;
                {fam_rule}
                padding: 6px {h_pad}px 24px {h_pad}px;
            }}
        """)

    def set_font_size(self, size_pt: int) -> None:
        """Set the editor base font size in points and update stylesheet."""
        self._font_size_pt = max(8, min(40, size_pt))
        font = self.font()
        font.setPointSize(self._font_size_pt)
        if hasattr(self, "_font_family") and self._font_family and self._font_family != "System":
            font.setFamily(self._font_family)
        self.setFont(font)
        self.document().setDefaultFont(font)
        metrics = self.fontMetrics()
        self.setTabStopDistance(float(metrics.horizontalAdvance(' ') * getattr(self, "_tab_size", 2)))
        self._refresh_editor_style()
        self._schedule_margin_update(full=True)
        self.viewport().update()

    def zoom_in(self, step: int = 1) -> None:
        """Increase editor font point size within comfortable bounds (min 8, max 40)."""
        cur_size = getattr(self, "_font_size_pt", 12)
        new_size = min(40, cur_size + step)
        if new_size != cur_size:
            self.set_font_size(new_size)
            self.zoom_changed.emit(new_size)

    def zoom_out(self, step: int = 1) -> None:
        """Decrease editor font point size within comfortable bounds (min 8, max 40)."""
        cur_size = getattr(self, "_font_size_pt", 12)
        new_size = max(8, cur_size - step)
        if new_size != cur_size:
            self.set_font_size(new_size)
            self.zoom_changed.emit(new_size)

    def zoom_reset(self, default_size: int = 12) -> None:
        """Reset editor font size to standard default (12px)."""
        self.set_font_size(default_size)
        self.zoom_changed.emit(default_size)

    def toggle_word_wrap(self) -> bool:
        """Toggle soft line wrapping between WidgetWidth and NoWrap."""
        is_wrapped = (self.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth)
        new_wrapped = not is_wrapped
        self.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth if new_wrapped else QTextEdit.LineWrapMode.NoWrap
        )
        if new_wrapped and hasattr(self, "_transient_h_scrollbar"):
            self._transient_h_scrollbar.hide_immediately()
        self.word_wrap_toggled.emit(new_wrapped)
        return new_wrapped

    def focusOutEvent(self, event) -> None:
        if self.slash_palette.isVisible() and not self.slash_palette.hasFocus():
            self.slash_palette.hide()
        if hasattr(self, "format_toolbar") and self.format_toolbar.isVisible() and not self.format_toolbar.hasFocus():
            self.format_toolbar.hide()
        super().focusOutEvent(event)

    def _on_selection_changed(self) -> None:
        """Show or hide the floating format toolbar based on current text selection."""
        cursor = self.textCursor()
        if not cursor.hasSelection() or not cursor.selectedText().strip():
            if hasattr(self, "format_toolbar") and self.format_toolbar.isVisible():
                self.format_toolbar.hide()
            return

        if self.slash_palette.isVisible():
            return

        self._show_format_toolbar()

    def _show_format_toolbar(self) -> None:
        """Compute the bounding rectangle of selected text and anchor the toolbar above it."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        start_c = QTextCursor(cursor)
        start_c.setPosition(cursor.selectionStart())
        end_c = QTextCursor(cursor)
        end_c.setPosition(cursor.selectionEnd())

        r_start = self.cursorRect(start_c)
        r_end = self.cursorRect(end_c)

        sel_left = min(r_start.left(), r_end.left())
        sel_right = max(r_start.right(), r_end.right())
        sel_top = min(r_start.top(), r_end.top())
        sel_bottom = max(r_start.bottom(), r_end.bottom())

        sel_rect = QRect(sel_left, sel_top, max(24, sel_right - sel_left), max(16, sel_bottom - sel_top))
        global_top_left = self.viewport().mapToGlobal(sel_rect.topLeft())
        global_rect = QRect(global_top_left.x(), global_top_left.y(), sel_rect.width(), sel_rect.height())

        self.format_toolbar.show_above_rect(global_rect)

    def _apply_text_format(self, format_type: str) -> None:
        """Apply or toggle inline/block markdown formatting on selection or cursor position."""
        cursor = self.textCursor()

        # 1. Block-level list and checkbox formatting
        if format_type in ("bullet", "number", "todo", "checkbox"):
            has_orig_sel = cursor.hasSelection()
            start = cursor.selectionStart() if has_orig_sel else cursor.position()
            end = cursor.selectionEnd() if has_orig_sel else cursor.position()

            cursor.beginEditBlock()
            b_start = self.document().findBlock(start)
            b_end = self.document().findBlock(end)
            if b_end.position() == end and b_end.blockNumber() > b_start.blockNumber():
                b_end = b_end.previous()

            blocks = []
            curr = b_start
            while curr.isValid() and curr.blockNumber() <= b_end.blockNumber():
                blocks.append(curr)
                if curr == b_end:
                    break
                curr = curr.next()

            non_empty_blocks = [b for b in blocks if b.text().strip()]
            if format_type in ("todo", "checkbox"):
                all_formatted = bool(non_empty_blocks) and all(
                    re.match(r"^\s*[-*+]\s*\[[ xX]?\]\s*", b.text()) for b in non_empty_blocks
                )
            elif format_type == "bullet":
                all_formatted = bool(non_empty_blocks) and all(
                    re.match(r"^\s*[-*+]\s+(?!\[[ xX]?\])", b.text()) for b in non_empty_blocks
                )
            else:
                all_formatted = bool(non_empty_blocks) and all(
                    re.match(r"^\s*\d+\.\s+", b.text()) for b in non_empty_blocks
                )

            for b in reversed(blocks):
                b_text = b.text()
                if not b_text.strip():
                    continue
                indent = b_text[: len(b_text) - len(b_text.lstrip())]
                content = b_text[len(indent) :]
                content_clean = re.sub(
                    r"^(\s*[-*+]\s*\[[ xX]?\]\s*|\s*[-*+]\s*|\s*\d+\.\s*)", "", content
                )

                if all_formatted:
                    new_line = indent + content_clean
                else:
                    if format_type in ("todo", "checkbox"):
                        new_line = indent + "- [ ] " + content_clean
                    elif format_type == "bullet":
                        new_line = indent + "- " + content_clean
                    else:
                        fwd_idx = non_empty_blocks.index(b) + 1
                        new_line = indent + f"{fwd_idx}. " + content_clean

                c = QTextCursor(b)
                c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                c.insertText(new_line)

            if has_orig_sel:
                sel_cursor = QTextCursor(self.document())
                sel_cursor.setPosition(b_start.position())
                sel_cursor.setPosition(b_end.position() + len(b_end.text()), QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(sel_cursor)
            else:
                new_c = QTextCursor(b_start)
                new_c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                self.setTextCursor(new_c)

            cursor.endEditBlock()
            self.viewport().update()
            if has_orig_sel:
                self._show_format_toolbar()
            elif hasattr(self, "format_toolbar"):
                self.format_toolbar.hide()
            return

        # 2. Link formatting
        if format_type == "link":
            if not cursor.hasSelection():
                cursor.select(QTextCursor.SelectionType.WordUnderCursor)
                sel_t = cursor.selectedText().strip()
                if sel_t and re.search(r"\w", sel_t):
                    self.setTextCursor(cursor)
                else:
                    cursor = self.textCursor()

            has_sel = self.textCursor().hasSelection()
            text = self.textCursor().selectedText() if has_sel else ""
            start = self.textCursor().selectionStart() if has_sel else self.textCursor().position()
            end = self.textCursor().selectionEnd() if has_sel else self.textCursor().position()

            struct_match = re.match(
                r"^(\s*(?:>+\s*)*(?:[-*+]\s*\[[ xX]?\]\s*|[-*+]\s+|\d+\.\s+|#{1,6}\s+))(.*)$",
                text,
            )
            lead_prefix = struct_match.group(1) if struct_match else ""
            core_text = struct_match.group(2) if struct_match else text

            existing_match = re.match(r"^\[(.*?)\]\((.*?)\)$", core_text.strip())
            if existing_match:
                init_text = existing_match.group(1)
                init_url = existing_match.group(2)
            else:
                init_text = core_text
                init_url = ""
                cb = QApplication.clipboard().text().strip()
                if cb.startswith(("http://", "https://", "mailto:")) and "\n" not in cb:
                    init_url = cb

            if hasattr(self, "format_toolbar") and self.format_toolbar.isVisible():
                self.format_toolbar.hide()

            link_text, link_url, accepted = ModernLinkDialog.get_link_data(
                self, initial_text=init_text, initial_url=init_url
            )
            if not accepted:
                return

            if not link_text and not link_url:
                return

            if not link_text:
                link_text = link_url

            if link_url:
                if not link_url.startswith(("http://", "https://", "mailto:", "file:", "#", "/", "./", "../")):
                    link_url = "https://" + link_url
                formatted = f"{lead_prefix}[{link_text}]({link_url})"
            else:
                formatted = f"{lead_prefix}{link_text}"

            cur = self.textCursor()
            cur.beginEditBlock()
            cur.insertText(formatted)
            new_cursor = self.textCursor()
            new_cursor.setPosition(start)
            new_cursor.setPosition(start + len(formatted), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(new_cursor)
            cur.endEditBlock()
            self.viewport().update()
            if self.textCursor().hasSelection():
                self._show_format_toolbar()
            return

        # 3. Inline formatting (bold, italic, strike, underline, code)
        if format_type == "bold":
            prefix, suffix = "**", "**"
        elif format_type == "italic":
            prefix, suffix = "*", "*"
        elif format_type == "strike":
            prefix, suffix = "~~", "~~"
        elif format_type == "underline":
            prefix, suffix = "<u>", "</u>"
        elif format_type == "code":
            prefix, suffix = "`", "`"
        else:
            return

        p_len = len(prefix)
        s_len = len(suffix)

        if not cursor.hasSelection():
            pos = cursor.position()
            doc_text = self.document().toPlainText()

            # 1. Check if cursor is already inside empty delimiter pair (e.g. **|**) -> delete it
            if pos >= p_len and pos + s_len <= len(doc_text):
                if doc_text[pos - p_len : pos] == prefix and doc_text[pos : pos + s_len] == suffix:
                    cursor.beginEditBlock()
                    del_c = QTextCursor(self.document())
                    del_c.setPosition(pos - p_len)
                    del_c.setPosition(pos + s_len, QTextCursor.MoveMode.KeepAnchor)
                    del_c.removeSelectedText()
                    cursor.endEditBlock()
                    self.viewport().update()
                    return

            # 2. Check if cursor is adjacent to any non-whitespace character (next to a word, bracket, or punctuation)
            ch_prev = doc_text[pos - 1] if pos > 0 else ""
            ch_next = doc_text[pos] if pos < len(doc_text) else ""
            if (ch_prev and not ch_prev.isspace()) or (ch_next and not ch_next.isspace()):
                # Caret is next to or touching a word without explicit selection -> do nothing
                return

            # 3. The place is empty (blank line, whitespace, or empty task line) -> insert delimiter pair and place caret inside
            c = self.textCursor()
            c.beginEditBlock()
            c.insertText(prefix + suffix)
            c.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, s_len)
            self.setTextCursor(c)
            c.endEditBlock()
            self.viewport().update()
            return

        cursor = self.textCursor()
        text = cursor.selectedText()
        if not text:
            return

        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        cursor.beginEditBlock()

        # Intelligently protect structural prefixes (- [ ] , - [x] , - , 1. , > , # )
        struct_match = re.match(
            r"^(\s*(?:>+\s*)*(?:[-*+]\s*\[[ xX]?\]\s*|[-*+]\s+|\d+\.\s+|#{1,6}\s+))(.*)$",
            text,
        )
        lead_prefix = struct_match.group(1) if struct_match else ""
        core_text = struct_match.group(2) if struct_match else text

        # 1. Check if core_text itself is already wrapped in prefix/suffix
        if core_text.startswith(prefix) and core_text.endswith(suffix) and len(core_text) >= p_len + s_len:
            unwrapped = core_text[p_len:-s_len]
            formatted = f"{lead_prefix}{unwrapped}"
            cursor.insertText(formatted)
            new_cursor = self.textCursor()
            new_cursor.setPosition(start)
            new_cursor.setPosition(start + len(formatted), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(new_cursor)
        else:
            # 2. Check if surrounding characters in document are already prefix/suffix
            doc_text = self.document().toPlainText()
            has_surrounding = False
            core_start = start + len(lead_prefix)
            core_end = end
            if core_start >= p_len and core_end + s_len <= len(doc_text):
                if doc_text[core_start - p_len : core_start] == prefix and doc_text[core_end : core_end + s_len] == suffix:
                    has_surrounding = True

            if has_surrounding:
                del_cursor = QTextCursor(self.document())
                del_cursor.setPosition(core_end)
                del_cursor.setPosition(core_end + s_len, QTextCursor.MoveMode.KeepAnchor)
                del_cursor.removeSelectedText()
                del_cursor.setPosition(core_start - p_len)
                del_cursor.setPosition(core_start, QTextCursor.MoveMode.KeepAnchor)
                del_cursor.removeSelectedText()

                new_cursor = self.textCursor()
                new_cursor.setPosition(core_start - p_len)
                new_cursor.setPosition(core_end - p_len, QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(new_cursor)
            else:
                formatted = f"{lead_prefix}{prefix}{core_text}{suffix}"
                cursor.insertText(formatted)
                new_cursor = self.textCursor()
                new_cursor.setPosition(start)
                new_cursor.setPosition(start + len(formatted), QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(new_cursor)

        cursor.endEditBlock()
        self.viewport().update()
        if self.textCursor().hasSelection():
            self._show_format_toolbar()

    def _apply_text_color(self, color: str) -> None:
        """Apply, change, or remove inline text color across single or multi-line selections."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        doc_text = self.document().toPlainText()
        new_start, new_end = expand_selection_to_color_tags(doc_text, start, end, "span")
        if (new_start, new_end) != (start, end):
            cursor.setPosition(new_start)
            cursor.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            start = new_start

        text = self.textCursor().selectedText()
        if not text:
            return

        formatted = apply_text_color_to_markdown(text, color)

        cursor.beginEditBlock()
        cursor.insertText(formatted)
        new_cursor = self.textCursor()
        new_cursor.setPosition(start)
        new_cursor.setPosition(start + len(formatted), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(new_cursor)
        cursor.endEditBlock()
        self.viewport().update()
        if self.textCursor().hasSelection():
            self._show_format_toolbar()

    def _apply_highlight_color(self, color: str) -> None:
        """Apply, change, or remove inline background highlight across single or multi-line selections."""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        doc_text = self.document().toPlainText()
        new_start, new_end = expand_selection_to_color_tags(doc_text, start, end, "mark")
        if (new_start, new_end) != (start, end):
            cursor.setPosition(new_start)
            cursor.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            start = new_start

        text = self.textCursor().selectedText()
        if not text:
            return

        formatted = apply_highlight_color_to_markdown(text, color)

        cursor.beginEditBlock()
        cursor.insertText(formatted)
        new_cursor = self.textCursor()
        new_cursor.setPosition(start)
        new_cursor.setPosition(start + len(formatted), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(new_cursor)
        cursor.endEditBlock()
        self.viewport().update()
        if self.textCursor().hasSelection():
            self._show_format_toolbar()

    def _apply_block_heading(self, level: int) -> None:
        """Apply or toggle markdown heading level (1 to 6) on current block or selection."""
        level = max(1, min(6, level))
        target_prefix = "#" * level + " "

        cursor = self.textCursor()
        has_sel = cursor.hasSelection()
        start = cursor.selectionStart() if has_sel else cursor.position()
        end = cursor.selectionEnd() if has_sel else cursor.position()

        b_start = self.document().findBlock(start)
        b_end = self.document().findBlock(end)
        if b_end.position() == end and b_end.blockNumber() > b_start.blockNumber():
            b_end = b_end.previous()

        blocks = []
        curr = b_start
        while curr.isValid() and curr.blockNumber() <= b_end.blockNumber():
            blocks.append(curr)
            if curr == b_end:
                break
            curr = curr.next()

        non_empty = [b for b in blocks if b.text().strip()]
        all_match_target = bool(non_empty) and all(
            re.match(r"^\s*" + re.escape(target_prefix), b.text()) for b in non_empty
        )

        cursor.beginEditBlock()
        for b in reversed(blocks):
            b_text = b.text()
            if not b_text.strip():
                continue
            indent = b_text[: len(b_text) - len(b_text.lstrip())]
            content = b_text[len(indent) :]
            cleaned = re.sub(r"^(#{1,6}\s+|[-*+]\s*(\[[ xX]?\])?\s*|\d+\.\s*)", "", content)

            if all_match_target:
                new_line = indent + cleaned
            else:
                new_line = indent + target_prefix + cleaned

            c = QTextCursor(b)
            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            c.insertText(new_line)

        if has_sel:
            sel_cursor = QTextCursor(self.document())
            sel_cursor.setPosition(b_start.position())
            sel_cursor.setPosition(b_end.position() + len(b_end.text()), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(sel_cursor)
        else:
            new_c = QTextCursor(b_start)
            new_c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self.setTextCursor(new_c)

        cursor.endEditBlock()
        self.viewport().update()

    def _apply_blockquote(self) -> None:
        """Toggle blockquote (>) on current block or selection."""
        cursor = self.textCursor()
        has_sel = cursor.hasSelection()
        start = cursor.selectionStart() if has_sel else cursor.position()
        end = cursor.selectionEnd() if has_sel else cursor.position()

        b_start = self.document().findBlock(start)
        b_end = self.document().findBlock(end)
        if b_end.position() == end and b_end.blockNumber() > b_start.blockNumber():
            b_end = b_end.previous()

        blocks = []
        curr = b_start
        while curr.isValid() and curr.blockNumber() <= b_end.blockNumber():
            blocks.append(curr)
            if curr == b_end:
                break
            curr = curr.next()

        non_empty = [b for b in blocks if b.text().strip()]
        all_quoted = bool(non_empty) and all(
            re.match(r"^\s*>\s*", b.text()) for b in non_empty
        )

        cursor.beginEditBlock()
        for b in reversed(blocks):
            b_text = b.text()
            if not b_text.strip():
                continue
            indent = b_text[: len(b_text) - len(b_text.lstrip())]
            content = b_text[len(indent) :]

            if all_quoted:
                cleaned = re.sub(r"^>\s?", "", content)
                new_line = indent + cleaned
            else:
                new_line = indent + "> " + content

            c = QTextCursor(b)
            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            c.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            c.insertText(new_line)

        if has_sel:
            sel_cursor = QTextCursor(self.document())
            sel_cursor.setPosition(b_start.position())
            sel_cursor.setPosition(b_end.position() + len(b_end.text()), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(sel_cursor)
        else:
            new_c = QTextCursor(b_start)
            new_c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            self.setTextCursor(new_c)

        cursor.endEditBlock()
        self.viewport().update()

    def _apply_code_block(self) -> None:
        """Insert or wrap selection in a fenced code block."""
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            sel_text = cursor.selectedText().replace("\u2029", "\n")
            if sel_text.startswith("```") and sel_text.rstrip().endswith("```"):
                lines = sel_text.splitlines()
                if len(lines) >= 2:
                    unwrapped = "\n".join(lines[1:-1])
                    cursor.insertText(unwrapped)
                    cursor.endEditBlock()
                    self.viewport().update()
                    return
            formatted = f"```\n{sel_text}\n```"
            start = cursor.selectionStart()
            cursor.insertText(formatted)
            sel_c = self.textCursor()
            sel_c.setPosition(start)
            sel_c.setPosition(start + len(formatted), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(sel_c)
        else:
            block = cursor.block()
            pos_in_b = cursor.positionInBlock()
            prefix_nl = "\n" if pos_in_b > 0 and block.text()[:pos_in_b].strip() else ""
            cursor.insertText(f"{prefix_nl}```\n\n```")
            cursor.movePosition(QTextCursor.MoveOperation.PreviousBlock)
            self.setTextCursor(cursor)
        cursor.endEditBlock()
        self.viewport().update()

    def _show_shortcuts_dialog(self) -> None:
        """Open the modern keyboard shortcuts reference cheatsheet modal."""
        from ui.shortcuts_dialog import ModernShortcutsDialog
        ModernShortcutsDialog.show_shortcuts(self.window())


    def find_matches(
        self, query: str, match_case: bool = False, whole_word: bool = False
    ) -> Tuple[int, int]:
        """Scan document for occurrences, highlight with ExtraSelection, and return (current_1_based, total)."""
        self._search_query = query
        self._search_case = match_case
        self._search_word = whole_word

        if not query:
            self.clear_search()
            return (0, 0)

        text = self.document().toPlainText()
        pattern = re.escape(query)
        if whole_word:
            pattern = r"\b" + pattern + r"\b"

        re_flags = 0 if match_case else re.IGNORECASE
        try:
            compiled = re.compile(pattern, re_flags)
        except re.error:
            self.clear_search()
            return (0, 0)

        matches = [(m.start(), m.end()) for m in compiled.finditer(text)]
        if not matches:
            self._search_matches = []
            self._current_search_idx = -1
            self.setExtraSelections([])
            self.viewport().update()
            return (0, 0)

        self._search_matches = matches

        # Select match nearest to current cursor position
        cursor_pos = self.textCursor().selectionStart()
        nearest_idx = 0
        for i, (start, end) in enumerate(matches):
            if start <= cursor_pos <= end or start >= cursor_pos:
                nearest_idx = i
                break

        self._current_search_idx = nearest_idx
        self._apply_search_highlights(scroll_to_active=True)
        return (self._current_search_idx + 1, len(matches))

    def find_next(self) -> Tuple[int, int]:
        """Jump to the next search occurrence and scroll it into view."""
        if not self._search_matches:
            return (0, 0)
        self._current_search_idx = (self._current_search_idx + 1) % len(self._search_matches)
        self._apply_search_highlights(scroll_to_active=True)
        return (self._current_search_idx + 1, len(self._search_matches))

    def find_prev(self) -> Tuple[int, int]:
        """Jump to the previous search occurrence and scroll it into view."""
        if not self._search_matches:
            return (0, 0)
        self._current_search_idx = (self._current_search_idx - 1) % len(self._search_matches)
        self._apply_search_highlights(scroll_to_active=True)
        return (self._current_search_idx + 1, len(self._search_matches))

    def replace_current(self, replacement: str) -> Tuple[int, int]:
        """Replace the active match and advance to the next match."""
        if not self._search_matches or self._current_search_idx < 0:
            return (0, 0)

        start, end = self._search_matches[self._current_search_idx]
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)
        cursor.endEditBlock()

        # Place cursor right after the newly inserted replacement
        new_c = self.textCursor()
        new_c.setPosition(start + len(replacement))
        self.setTextCursor(new_c)

        return self.find_matches(self._search_query, self._search_case, self._search_word)

    def replace_all(
        self, query: str, replacement: str, match_case: bool = False, whole_word: bool = False
    ) -> int:
        """Atomically replace all matches in the document in a single undo block."""
        if not query:
            return 0

        text = self.document().toPlainText()
        pattern = re.escape(query)
        if whole_word:
            pattern = r"\b" + pattern + r"\b"

        re_flags = 0 if match_case else re.IGNORECASE
        try:
            compiled = re.compile(pattern, re_flags)
        except re.error:
            return 0

        matches = [(m.start(), m.end()) for m in compiled.finditer(text)]
        if not matches:
            return 0

        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        for start, end in reversed(matches):
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(replacement)
        cursor.endEditBlock()

        self.clear_search()
        self.viewport().update()
        return len(matches)

    def clear_search(self) -> None:
        """Clear all search highlights, matches, and state."""
        self._search_matches = []
        self._current_search_idx = -1
        self._search_query = ""
        self.setExtraSelections([])
        self.viewport().update()

    def _apply_search_highlights(self, scroll_to_active: bool = True) -> None:
        """Apply visual highlights for all search matches via QTextEdit.ExtraSelection."""
        if not self._search_matches:
            self.setExtraSelections([])
            return

        selections = []
        doc = self.document()

        for i, (start, end) in enumerate(self._search_matches):
            sel = QTextEdit.ExtraSelection()
            c = QTextCursor(doc)
            c.setPosition(start)
            c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = c

            if i == self._current_search_idx:
                sel.format.setBackground(QColor("#0a84ff"))
                sel.format.setForeground(QColor("#ffffff"))
                if scroll_to_active:
                    self.setTextCursor(c)
                    self.ensureCursorVisible()
            else:
                sel.format.setBackground(QColor(235, 175, 40, 95))
                sel.format.setForeground(QColor("#ffffff"))

            selections.append(sel)

        self.setExtraSelections(selections)
        self.viewport().update()

    def _show_slash_palette(self) -> None:
        """Position and display the floating slash palette directly beneath the cursor."""
        cursor_rect = self.cursorRect()
        global_pos = self.viewport().mapToGlobal(cursor_rect.bottomLeft())
        palette_w = self.slash_palette.width()
        palette_h = self.slash_palette.height()

        x = global_pos.x()
        y = global_pos.y() + 4

        # Keep on screen if near edges
        screen = self.screen()
        if screen:
            screen_geom = screen.availableGeometry()
            if y + palette_h > screen_geom.bottom():
                top_pos = self.viewport().mapToGlobal(cursor_rect.topLeft())
                y = top_pos.y() - palette_h - 4
            if x + palette_w > screen_geom.right():
                x = screen_geom.right() - palette_w - 8

        self.slash_palette.move(x, y)
        self.slash_palette.populate("")
        self.slash_palette.show()
        self.slash_palette.raise_()

    def _on_slash_command_selected(self, cmd: SlashCommand) -> None:
        """Replace the typed slash query with the selected Markdown block syntax."""
        self.slash_palette.hide()
        cursor = self.textCursor()
        block = cursor.block()
        b_text = block.text()

        # Determine the slash position
        slash_pos = self._slash_start_pos - 1 if self._slash_start_pos is not None else None
        if slash_pos is None or slash_pos < block.position() or slash_pos > cursor.position():
            b_offset = cursor.positionInBlock()
            last_slash = b_text.rfind("/", 0, b_offset)
            if last_slash != -1:
                slash_pos = block.position() + last_slash
            else:
                slash_pos = cursor.position()

        cursor.beginEditBlock()

        if cmd.id == "code":
            replace_cursor = QTextCursor(self.document())
            replace_cursor.setPosition(slash_pos)
            replace_cursor.setPosition(cursor.position(), QTextCursor.MoveMode.KeepAnchor)
            b_offset = slash_pos - block.position()
            prefix_nl = "\n" if b_offset > 0 and b_text[:b_offset].strip() else ""
            replace_cursor.insertText(f"{prefix_nl}```\n\n```")
            target_pos = slash_pos + len(prefix_nl) + 4
            c = QTextCursor(self.document())
            c.setPosition(target_pos)
            self.setTextCursor(c)
        elif cmd.id == "inline_code":
            replace_cursor = QTextCursor(self.document())
            replace_cursor.setPosition(slash_pos)
            replace_cursor.setPosition(cursor.position(), QTextCursor.MoveMode.KeepAnchor)
            replace_cursor.insertText("``")
            c = QTextCursor(self.document())
            c.setPosition(slash_pos + 1)
            self.setTextCursor(c)
        elif cmd.id == "divider":
            replace_cursor = QTextCursor(self.document())
            replace_cursor.setPosition(slash_pos)
            replace_cursor.setPosition(cursor.position(), QTextCursor.MoveMode.KeepAnchor)
            replace_cursor.insertText(cmd.prefix)
            self.setTextCursor(replace_cursor)
        elif cmd.id == "date":
            # Remove the typed slash query text
            replace_cursor = QTextCursor(self.document())
            replace_cursor.setPosition(slash_pos)
            replace_cursor.setPosition(cursor.position(), QTextCursor.MoveMode.KeepAnchor)
            replace_cursor.removeSelectedText()
            cursor.endEditBlock()
            self._slash_start_pos = None

            dlg = ModernDatePickerDialog(parent=self)
            if dlg.exec():
                chosen_date = dlg.selected_date
                date_str = chosen_date.isoformat()

                cur_block = self.textCursor().block()
                cur_text = cur_block.text().strip()

                ins_cursor = QTextCursor(self.document())
                if not cur_text:
                    # Current line is empty: replace with date badge and move to clean newline
                    ins_cursor.setPosition(cur_block.position())
                    ins_cursor.beginEditBlock()
                    ins_cursor.insertText(f"@date({date_str})\n")
                    ins_cursor.endEditBlock()
                    self.setTextCursor(ins_cursor)
                else:
                    # Current line has content: always insert date badge on clean newline below
                    ins_cursor.setPosition(cur_block.position() + cur_block.length() - 1)
                    ins_cursor.beginEditBlock()
                    ins_cursor.insertText(f"\n@date({date_str})\n")
                    ins_cursor.endEditBlock()
                    self.setTextCursor(ins_cursor)

            self.setFocus()
            self.ensureCursorVisible()
            self.viewport().update()
            return
        else:
            # Line-level formatting command (checkbox, bullet, number, h1, h2, h3, quote)
            # Transform current line to the requested block format regardless of previous format
            b_slash_offset = slash_pos - block.position()
            b_end_offset = cursor.positionInBlock()
            text_before = b_text[:b_slash_offset].rstrip()
            text_after = b_text[b_end_offset:]
            line_content = text_before + text_after

            new_line = transform_line_block_prefix(line_content, cmd.prefix)

            # Replace the entire block with the transformed line
            line_cursor = QTextCursor(block)
            line_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            line_cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            line_cursor.insertText(new_line)

            # Place cursor at the appropriate position in the transformed line
            if text_after:
                new_cursor_offset = max(0, min(len(new_line), len(new_line) - len(line_content) + b_slash_offset))
                target_pos = block.position() + new_cursor_offset
            else:
                target_pos = block.position() + len(new_line)

            end_cursor = QTextCursor(self.document())
            end_cursor.setPosition(target_pos)
            self.setTextCursor(end_cursor)

        cursor.endEditBlock()
        self._slash_start_pos = None
        self.setFocus()
        self.ensureCursorVisible()
        self.viewport().update()

    def _reset_copied_state(self) -> None:
        """Reset the copy button feedback to default."""
        self._copied_code_block = None
        self.viewport().update()

    def _get_table_rect(self, tr: TableRegion) -> Optional[QRectF]:
        """Compute the geometry QRectF of an inactive rendered table card."""
        b_top = self.document().findBlockByNumber(tr.start_block)
        b_bot = self.document().findBlockByNumber(tr.end_block)
        if not (b_top.isValid() and b_bot.isValid()):
            return None
        r_top = self.cursorRect(QTextCursor(b_top))
        r_bot = self.cursorRect(QTextCursor(b_bot))
        avail_w = max(100.0, float(self.viewport().width() - r_top.left() - 28))
        return QRectF(float(r_top.left()), float(r_top.top()), avail_w, float(r_bot.bottom() - r_top.top()))

    def _get_code_card_rect(self, cr: CodeRegion) -> Optional[QRectF]:
        """Compute the tightly bounded geometry QRectF of an inactive rendered code card."""
        b_top = self.document().findBlockByNumber(cr.start_block)
        b_bot = self.document().findBlockByNumber(cr.end_block)
        if not (b_top.isValid() and b_bot.isValid()):
            return None
        r_top = self.cursorRect(QTextCursor(b_top))
        r_bot = self.cursorRect(QTextCursor(b_bot))

        scale = getattr(self, "ui_scale", 1.0)
        avail_w = max(100.0, float(self.viewport().width() - r_top.left() - 28.0))
        header_h = round(28.0 * scale)
        line_h = round(22.0 * scale)
        top_pad = round(8.0 * scale)
        bot_pad = round(16.0 * scale)
        card_h = float(header_h + top_pad + len(cr.lines) * line_h + bot_pad)
        return QRectF(float(r_top.left()), float(r_top.top()), avail_w, card_h)

    def _schedule_margin_update(
        self,
        *,
        blocks: Optional[Set[int]] = None,
        full: bool = False,
    ) -> None:
        """Queue a debounced block-margin update for either specific dirty blocks or the full document."""
        if full or blocks is None:
            self._dirty_margin_blocks = None
        elif self._dirty_margin_blocks is not None:
            self._dirty_margin_blocks.update(blocks)
        self._margin_timer.start()

    def _flush_deferred_regions(self) -> None:
        """Run debounced full-document region scan for large notes and rehighlight changed blocks."""
        changed = self.highlighter.refresh_regions()
        if changed:
            doc = self.document()
            for b_num in changed:
                b = doc.findBlockByNumber(b_num)
                if b.isValid():
                    self.highlighter.rehighlightBlock(b)
            self._schedule_margin_update(blocks=changed)
        self.viewport().update()

    def _update_block_margins(self) -> None:
        """Ensure blockquotes, list items, checkboxes, and inactive code blocks have calibrated line heights."""
        if self._updating_margins:
            return
        self._updating_margins = True
        dirty_blocks = self._dirty_margin_blocks
        self._dirty_margin_blocks = set()
        try:
            doc = self.document()
            cur = QTextCursor(doc)
            cur.beginEditBlock()
            font = self.font()
            fm = QFontMetricsF(font)
            scale = getattr(self, "ui_scale", 1.0)
            active_bn = self.highlighter.active_block_number

            inactive_code_blocks: dict[int, tuple[float, bool]] = {}
            header_h = round(28.0 * scale)
            line_h = round(22.0 * scale)
            top_pad = round(8.0 * scale)
            bot_pad = round(16.0 * scale)
            for cr in self.highlighter.code_regions:
                if not (cr.start_block <= active_bn <= cr.end_block):
                    inactive_code_blocks[cr.start_block] = (float(header_h + top_pad), True)
                    for b_num in range(cr.start_block + 1, cr.end_block):
                        inactive_code_blocks[b_num] = (float(line_h), True)
                    inactive_code_blocks[cr.end_block] = (float(bot_pad + round(9.0 * scale)), True)

            inactive_video_blocks: dict[int, tuple[float, bool]] = {}
            if self.highlighter.video_regions:
                avail_w = max(200.0, float(self.viewport().width() - 2 * self._horizontal_padding))
                _, card_h = get_video_card_dimensions(avail_w, ui_scale=scale)
                card_h_with_margin = card_h + round(12.0 * scale)
                for vr in self.highlighter.video_regions:
                    if not (vr.start_block <= active_bn <= vr.end_block):
                        count = max(1, vr.end_block - vr.start_block + 1)
                        if count == 1:
                            inactive_video_blocks[vr.start_block] = (float(card_h_with_margin), True)
                        else:
                            per_block_h = float(card_h_with_margin / count)
                            for b_num in range(vr.start_block, vr.end_block + 1):
                                inactive_video_blocks[b_num] = (per_block_h, True)

            def _apply_to_block(b: QTextBlock) -> None:
                b_num = b.blockNumber()
                text = b.text()
                target_margin = 0.0
                target_indent = 0.0
                if b.userState() != 1:
                    target_margin, target_indent = calculate_block_hanging_indent(
                        text, font, ui_scale=scale, fm=fm
                    )

                if b_num in inactive_code_blocks:
                    target_lh, target_nb = inactive_code_blocks[b_num]
                    target_lh_type = QTextBlockFormat.LineHeightTypes.FixedHeight.value
                elif b_num in inactive_video_blocks:
                    target_lh, target_nb = inactive_video_blocks[b_num]
                    target_lh_type = QTextBlockFormat.LineHeightTypes.FixedHeight.value
                else:
                    target_lh = 120.0
                    target_lh_type = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
                    target_nb = False

                bf = b.blockFormat()
                changed = False
                if abs(bf.leftMargin() - target_margin) > 0.5:
                    bf.setLeftMargin(target_margin)
                    changed = True
                if abs(bf.textIndent() - target_indent) > 0.5:
                    bf.setTextIndent(target_indent)
                    changed = True
                if abs(bf.lineHeight() - target_lh) > 0.5 or bf.lineHeightType() != target_lh_type:
                    bf.setLineHeight(target_lh, target_lh_type)
                    changed = True
                if bf.nonBreakableLines() != target_nb:
                    bf.setNonBreakableLines(target_nb)
                    changed = True
                if changed:
                    c = QTextCursor(b)
                    c.setBlockFormat(bf)

            try:
                if dirty_blocks is None:
                    b = doc.firstBlock()
                    while b.isValid():
                        _apply_to_block(b)
                        b = b.next()
                else:
                    for b_num in sorted(dirty_blocks):
                        b = doc.findBlockByNumber(b_num)
                        if b.isValid():
                            _apply_to_block(b)
            finally:
                cur.endEditBlock()
        finally:
            self._updating_margins = False

    def _update_blockquote_margins(self) -> None:
        """Backward-compatible alias for full-document _update_block_margins."""
        self._dirty_margin_blocks = None
        self._update_block_margins()

    def setPlainText(self, text: str) -> None:
        """Set editor plain text, reset undo history, refresh regions, and apply block margins in one pass."""
        self._margin_timer.stop()
        self._region_timer.stop()
        self._pending_text_mutation = False
        self._resetting_text = True
        try:
            super().setPlainText(text)
            cur = self.textCursor()
            self._last_block_count = self.document().blockCount()
            self.highlighter.active_block_number = cur.block().blockNumber()
            self.highlighter.cursor_pos_in_block = cur.positionInBlock()
            changed = self.highlighter.refresh_regions()
            self._dirty_margin_blocks = None
            self._update_block_margins()
            if changed:
                doc = self.document()
                for b_num in changed:
                    b = doc.findBlockByNumber(b_num)
                    if b.isValid():
                        self.highlighter.rehighlightBlock(b)
            self.undo_manager.reset(self.toPlainText(), cur.anchor(), cur.position())
        finally:
            self._resetting_text = False

    def canUndo(self) -> bool:
        """Return True if at least one plain-text undo step is available."""
        return self.undo_manager.can_undo

    def canRedo(self) -> bool:
        """Return True if at least one plain-text redo step is available."""
        return self.undo_manager.can_redo

    def undo(self) -> None:
        """Restore the previous plain-text state and exact cursor/selection without layout pollution."""
        step = self.undo_manager.undo()
        if step is not None:
            self._apply_history_step(step)

    def redo(self) -> None:
        """Re-apply the next undone plain-text state and exact cursor/selection."""
        step = self.undo_manager.redo()
        if step is not None:
            self._apply_history_step(step)

    def _apply_history_step(self, step: Tuple[int, int, str, int, int]) -> None:
        """Apply a reversible plain-text delta to QTextDocument and refresh margins and highlights."""
        replace_start, replace_end, replacement, target_anchor, target_pos = step
        self._margin_timer.stop()
        self._applying_undo_redo = True
        try:
            doc = self.document()
            edit_c = QTextCursor(doc)
            edit_c.setPosition(replace_start)
            if replace_end > replace_start:
                edit_c.setPosition(replace_end, QTextCursor.MoveMode.KeepAnchor)
            edit_c.insertText(replacement)

            doc_len = max(0, doc.characterCount() - 1)
            clamped_anchor = max(0, min(doc_len, target_anchor))
            clamped_pos = max(0, min(doc_len, target_pos))

            target_c = QTextCursor(doc)
            target_c.setPosition(clamped_anchor)
            if clamped_pos != clamped_anchor:
                target_c.setPosition(clamped_pos, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(target_c)

            self._dirty_margin_blocks = None
            self._update_block_margins()
            self._margin_timer.stop()
            self._region_timer.stop()
            self._last_block_count = doc.blockCount()
            self.highlighter.active_block_number = target_c.block().blockNumber()
            self.highlighter.cursor_pos_in_block = target_c.positionInBlock()
            changed = self.highlighter.refresh_regions()
            for b_num in changed:
                b = doc.findBlockByNumber(b_num)
                if b.isValid():
                    self.highlighter.rehighlightBlock(b)
            b_cur = target_c.block()
            if b_cur.isValid():
                self.highlighter.rehighlightBlock(b_cur)
            self.ensureCursorVisible()
            self.viewport().update()
        finally:
            self._applying_undo_redo = False

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Wire right-click menu Undo/Redo actions to the plain-text undo manager."""
        menu = self.createStandardContextMenu(event.pos())
        undo_seq = QKeySequence(QKeySequence.StandardKey.Undo)
        redo_seq = QKeySequence(QKeySequence.StandardKey.Redo)
        for act in list(menu.actions()):
            raw_text = act.text().replace("&", "")
            shortcuts = act.shortcuts()
            if raw_text.startswith("Undo") or undo_seq in shortcuts:
                undo_act = QAction("Undo", menu)
                undo_act.setShortcut(undo_seq)
                undo_act.setEnabled(self.undo_manager.can_undo)
                undo_act.triggered.connect(self.undo)
                menu.insertAction(act, undo_act)
                menu.removeAction(act)
            elif raw_text.startswith("Redo") or redo_seq in shortcuts:
                redo_act = QAction("Redo", menu)
                redo_act.setShortcut(redo_seq)
                redo_act.setEnabled(self.undo_manager.can_redo)
                redo_act.triggered.connect(self.redo)
                menu.insertAction(act, redo_act)
                menu.removeAction(act)
        menu.exec(event.globalPos())

    def insertFromMimeData(self, source: QMimeData) -> None:
        """Ensure pasted content is always inserted as clean Markdown / plain text in a single edit block."""
        if source.hasText():
            text = source.text()
            cursor = self.textCursor()
            cursor.beginEditBlock()
            try:
                cursor.insertText(text)
            finally:
                cursor.endEditBlock()
        else:
            super().insertFromMimeData(source)

    def _on_document_contents_change(
        self, position: int, chars_removed: int, chars_added: int
    ) -> None:
        """Track genuine text mutations and dirty block indices in O(1) before contentsChanged."""
        if self._updating_margins or self._resetting_text or self._applying_undo_redo:
            return
        if chars_removed > 0 or chars_added > 0:
            self._pending_text_mutation = True
            doc = self.document()
            b_start = doc.findBlock(position)
            b_end = doc.findBlock(position + chars_added)
            if b_start.isValid() and b_end.isValid():
                s_num = b_start.blockNumber()
                e_num = b_end.blockNumber()
                if e_num - s_num <= 25:
                    dirty = set(range(max(0, s_num - 1), e_num + 2))
                    if self._dirty_margin_blocks is not None:
                        self._dirty_margin_blocks.update(dirty)
                else:
                    self._dirty_margin_blocks = None
            else:
                self._dirty_margin_blocks = None

    def _on_contents_changed(self) -> None:
        """Recompute regions, record clean text diffs for undo/redo, and schedule dirty-block margins."""
        had_text_mutation = self._pending_text_mutation
        self._pending_text_mutation = False

        if self._updating_margins or self._resetting_text:
            return
        if not had_text_mutation and not self._applying_undo_redo:
            return

        doc = self.document()
        cursor = self.textCursor()
        cur_bn = cursor.block().blockNumber()
        new_block_count = doc.blockCount()
        block_delta = abs(new_block_count - self._last_block_count)
        self._last_block_count = new_block_count

        if not self._applying_undo_redo:
            if block_delta > 5:
                self._schedule_margin_update(full=True)
            else:
                dirty = {cur_bn}
                if block_delta > 0:
                    dirty.add(max(0, cur_bn - 1))
                    dirty.add(cur_bn + 1)
                self._schedule_margin_update(blocks=dirty)

            if had_text_mutation:
                self.undo_manager.record_change(
                    self.toPlainText(),
                    cursor.anchor(),
                    cursor.position(),
                    force_merge=self._cleaning_empty_tag,
                )

        self.highlighter.active_block_number = cur_bn
        self.highlighter.cursor_pos_in_block = cursor.positionInBlock()

        if new_block_count > 400 and not self._applying_undo_redo:
            self._region_timer.start()
        else:
            self._region_timer.stop()
            changed = self.highlighter.refresh_regions()
            for b_num in changed:
                b = doc.findBlockByNumber(b_num)
                if b.isValid():
                    self.highlighter.rehighlightBlock(b)
        self.viewport().update()

    def _on_cursor_position_changed(self) -> None:
        """Rehighlight lines and regions when the cursor moves between lines or across syntax boundaries."""
        cursor = self.textCursor()
        new_block = cursor.block()
        new_block_num = new_block.blockNumber()
        new_pos_in_block = cursor.positionInBlock()

        # Prevent caret from ever resting strictly inside invisible HTML color/mark tags
        if not cursor.hasSelection() and not self._applying_undo_redo and not self._resetting_text:
            b_text = new_block.text()
            if "<" in b_text or "mark" in b_text or "span" in b_text:
                # Remove empty tag pairs automatically
                empty_m = re.search(r"<{0,1}(?:mark|span|u)[^>]*>\s*</{0,1}(?:mark|span|u)>", b_text, re.IGNORECASE)
                if empty_m:
                    es, ee = empty_m.span()
                    clean_c = QTextCursor(self.document())
                    clean_c.setPosition(new_block.position() + es)
                    clean_c.setPosition(new_block.position() + ee, QTextCursor.MoveMode.KeepAnchor)
                    self._cleaning_empty_tag = True
                    try:
                        clean_c.removeSelectedText()
                    finally:
                        self._cleaning_empty_tag = False
                    b_text = new_block.text()
                    new_pos_in_block = self.textCursor().positionInBlock()

                for tm in re.finditer(r"<{0,1}(?:mark|span|u|/mark|/span|/u)[^>]*>", b_text, re.IGNORECASE):
                    ts, te = tm.span()
                    if ts < new_pos_in_block < te:
                        target_p = te if (new_pos_in_block - ts >= te - new_pos_in_block) else ts
                        snap_c = QTextCursor(cursor)
                        snap_c.setPosition(new_block.position() + target_p)
                        self.setTextCursor(snap_c)
                        return

        if not self._applying_undo_redo and not self._resetting_text and not self._pending_text_mutation:
            cur_now = self.textCursor()
            self.undo_manager.update_cursor(cur_now.anchor(), cur_now.position())

        old_block_num = self.highlighter.active_block_number
        old_pos_in_block = getattr(self.highlighter, "cursor_pos_in_block", -1)

        block_changed = new_block_num != old_block_num
        self.highlighter.active_block_number = new_block_num
        self.highlighter.cursor_pos_in_block = new_pos_in_block

        if block_changed:
            dirty_region_blocks: Set[int] = set()
            for cr in self.highlighter.code_regions:
                was_in = cr.start_block <= old_block_num <= cr.end_block
                is_in = cr.start_block <= new_block_num <= cr.end_block
                if was_in != is_in:
                    dirty_region_blocks.update(range(cr.start_block, cr.end_block + 1))
            for vr in self.highlighter.video_regions:
                was_in = vr.start_block <= old_block_num <= vr.end_block
                is_in = vr.start_block <= new_block_num <= vr.end_block
                if was_in != is_in:
                    dirty_region_blocks.update(range(vr.start_block, vr.end_block + 1))
            if dirty_region_blocks:
                self._schedule_margin_update(blocks=dirty_region_blocks)

            changed = self.highlighter.update_active_modes()
            changed.add(old_block_num)
            changed.add(new_block_num)
            for b_num in changed:
                b = self.document().findBlockByNumber(b_num)
                if b.isValid():
                    self.highlighter.rehighlightBlock(b)
        else:
            if new_pos_in_block != old_pos_in_block:
                self.highlighter.rehighlightBlock(new_block)

        self.viewport().update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint editor text, vector checkboxes, styled tables, math equations, and mermaid diagrams."""
        super().paintEvent(event)

        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        active_bn = self.highlighter.active_block_number
        vp_height = self.viewport().height()
        vp_width = self.viewport().width()

        cur = self.textCursor()
        has_sel = cur.hasSelection()
        sel_start = cur.selectionStart() if has_sel else -1
        sel_end = cur.selectionEnd() if has_sel else -1
        sel_start_b = self.document().findBlock(sel_start).blockNumber() if has_sel else -1
        sel_end_b = self.document().findBlock(sel_end).blockNumber() if has_sel else -1
        sel_bg_color = QColor("#264f87")

        self._rendered_block_rects.clear()

        # 1. Render Inactive Tables
        for tr in self.highlighter.table_regions:
            if tr.start_block <= active_bn <= tr.end_block:
                continue  # Active editing mode for this table
            b_top = self.document().findBlockByNumber(tr.start_block)
            b_bot = self.document().findBlockByNumber(tr.end_block)
            if not (b_top.isValid() and b_bot.isValid()):
                continue

            r_top = self.cursorRect(QTextCursor(b_top))
            r_bot = self.cursorRect(QTextCursor(b_bot))
            if r_top.top() > vp_height or r_bot.bottom() < 0:
                continue

            avail_w = max(100.0, float(vp_width - r_top.left() - 28))
            table_rect = QRectF(float(r_top.left()), float(r_top.top()), avail_w, float(r_bot.bottom() - r_top.top()))
            self._rendered_block_rects.append((tr.start_block, tr.end_block, table_rect))
            scroll_x = self._table_scroll_x.get(tr.start_block, 0.0)
            render_table(painter, table_rect, tr, self.font(), scroll_x=scroll_x)

            if has_sel and (tr.start_block <= sel_end_b and tr.end_block >= sel_start_b):
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(QColor("#0a84ff"), 1.2))
                painter.setBrush(QBrush(QColor(38, 79, 135, 120)))
                painter.drawRoundedRect(table_rect, 6.0, 6.0)
                painter.restore()

        # 2. Render Inactive Display Math ($$ ... $$)
        if self.render_latex:
            for mr in self.highlighter.math_regions:
                if mr.start_block <= active_bn <= mr.end_block:
                    continue
                b_top = self.document().findBlockByNumber(mr.start_block)
                b_bot = self.document().findBlockByNumber(mr.end_block)
                if not (b_top.isValid() and b_bot.isValid()):
                    continue

                r_top = self.cursorRect(QTextCursor(b_top))
                r_bot = self.cursorRect(QTextCursor(b_bot))
                if r_top.top() > vp_height or r_bot.bottom() < 0:
                    continue

                math_rect = QRectF(float(r_top.left()), float(r_top.top()), float(vp_width - r_top.left() - 28), float(r_bot.bottom() - r_top.top()))
                self._rendered_block_rects.append((mr.start_block, mr.end_block, math_rect))

                pix = render_math_to_pixmap(mr.latex, font_size=19.0, display_mode=True)
                log_w = pix.width() / pix.devicePixelRatio()
                log_h = pix.height() / pix.devicePixelRatio()
                px = math_rect.left() + max(0.0, (math_rect.width() - log_w) / 2.0)
                py = math_rect.top() + max(0.0, (math_rect.height() - log_h) / 2.0)
                painter.drawPixmap(QPointF(px, py), pix)

                if has_sel and (mr.start_block <= sel_end_b and mr.end_block >= sel_start_b):
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setPen(QPen(QColor("#0a84ff"), 1.2))
                    painter.setBrush(QBrush(QColor(38, 79, 135, 120)))
                    painter.drawRoundedRect(math_rect, 6.0, 6.0)
                    painter.restore()

        # 3. Render Inactive Mermaid Diagrams (```mermaid ... ```)
        if self.render_mermaid:
            for mmd in self.highlighter.mermaid_regions:
                if mmd.start_block <= active_bn <= mmd.end_block:
                    continue
                b_top = self.document().findBlockByNumber(mmd.start_block)
                b_bot = self.document().findBlockByNumber(mmd.end_block)
                if not (b_top.isValid() and b_bot.isValid()):
                    continue

                r_top = self.cursorRect(QTextCursor(b_top))
                r_bot = self.cursorRect(QTextCursor(b_bot))
                if r_top.top() > vp_height or r_bot.bottom() < 0:
                    continue

                mmd_rect = QRectF(float(r_top.left()), float(r_top.top()), float(vp_width - r_top.left() - 28), float(r_bot.bottom() - r_top.top()))
                self._rendered_block_rects.append((mmd.start_block, mmd.end_block, mmd_rect))

                pix = render_mermaid_to_pixmap(mmd.source)
                log_w = pix.width() / pix.devicePixelRatio()
                log_h = pix.height() / pix.devicePixelRatio()
                px = mmd_rect.left() + max(0.0, (mmd_rect.width() - log_w) / 2.0)
                py = mmd_rect.top() + max(0.0, (mmd_rect.height() - log_h) / 2.0)
                painter.drawPixmap(QPointF(px, py), pix)

                if has_sel and (mmd.start_block <= sel_end_b and mmd.end_block >= sel_start_b):
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    painter.setPen(QPen(QColor("#0a84ff"), 1.2))
                    painter.setBrush(QBrush(QColor(38, 79, 135, 120)))
                    painter.drawRoundedRect(mmd_rect, 6.0, 6.0)
                    painter.restore()

        # 4. Render Inactive Code Cards (```lang ... ```)
        for cr in self.highlighter.code_regions:
            if cr.start_block <= active_bn <= cr.end_block:
                continue

            card_rect = self._get_code_card_rect(cr)
            if card_rect is None:
                continue

            if card_rect.top() > vp_height or card_rect.bottom() < 0:
                continue

            self._rendered_block_rects.append((cr.start_block, cr.end_block, card_rect))
            scroll_x = self._code_scroll_x.get(cr.start_block, 0.0)
            is_copied = self._copied_code_block == cr.start_block
            is_copy_hovered = self._hovered_copy_btn == cr.start_block
            is_edit_hovered = self._hovered_edit_btn == cr.start_block
            render_code_card(
                painter,
                card_rect,
                cr,
                scroll_x=scroll_x,
                is_copied=is_copied,
                is_copy_hovered=is_copy_hovered,
                is_edit_hovered=is_edit_hovered,
                show_line_numbers=self.code_line_numbers,
                ui_scale=getattr(self, "ui_scale", 1.0),
            )

            if has_sel and (cr.start_block <= sel_end_b and cr.end_block >= sel_start_b):
                scale = getattr(self, "ui_scale", 1.0)
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(QColor("#0a84ff"), 1.2))
                painter.setBrush(QBrush(QColor(38, 79, 135, 120)))
                corner_r = round(8.0 * scale, 1)
                painter.drawRoundedRect(card_rect, corner_r, corner_r)
                painter.restore()

        # 4.5. Render Inactive Date Cards (@date(...))
        self._date_card_rects.clear()
        scale = getattr(self, "ui_scale", 1.0)
        card_h = round(52.0 * scale)
        for b_num, target_date in self.highlighter.date_blocks.items():
            if b_num == active_bn:
                continue
            b = self.document().findBlockByNumber(b_num)
            if not b.isValid():
                continue
            c = QTextCursor(b)
            r = self.cursorRect(c)
            if r.top() > vp_height or r.bottom() < 0:
                continue

            card_top = float(r.top()) + max(0.0, (float(r.height()) - card_h) / 2.0)
            avail_w = max(160.0, float(vp_width - r.left() - 28.0))
            card_rect = QRectF(float(r.left()), card_top, avail_w, card_h)
            self._date_card_rects[b_num] = (card_rect, target_date)
            self._rendered_block_rects.append((b_num, b_num, card_rect))
            is_hovered = self._hovered_date_block == b_num
            render_date_card(
                painter,
                card_rect,
                target_date,
                ui_scale=scale,
                is_hovered=is_hovered,
            )

            if has_sel and (sel_start_b <= b_num <= sel_end_b):
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(QColor("#0a84ff"), 1.2))
                painter.setBrush(QBrush(QColor(38, 79, 135, 120)))
                corner_r = round(10.0 * scale, 1)
                painter.drawRoundedRect(card_rect, corner_r, corner_r)
                painter.restore()

        # 4.6. Render Inactive YouTube Video Cards
        self._video_card_rects.clear()
        cache_mgr = YouTubeCacheManager.instance()
        doc_layout = self.document().documentLayout()
        scroll_y = float(self.verticalScrollBar().value())
        for vr in self.highlighter.video_regions:
            if vr.start_block <= active_bn <= vr.end_block:
                continue
            b_top = self.document().findBlockByNumber(vr.start_block)
            b_bot = self.document().findBlockByNumber(vr.end_block)
            if not (b_top.isValid() and b_bot.isValid()):
                continue

            top_doc_rect = doc_layout.blockBoundingRect(b_top)
            block_vp_top = float(top_doc_rect.top()) - scroll_y
            r_top = self.cursorRect(QTextCursor(b_top))

            avail_w = max(200.0, float(vp_width - 2 * self._horizontal_padding))
            card_w, card_h = get_video_card_dimensions(avail_w, ui_scale=scale)
            card_top = block_vp_top + round(6.0 * scale)
            card_rect = QRectF(float(r_top.left()), card_top, card_w, card_h)

            if card_rect.top() > vp_height or card_rect.bottom() < 0:
                continue
            self._video_card_rects[vr.start_block] = (card_rect, vr)
            self._rendered_block_rects.append((vr.start_block, vr.end_block, card_rect))

            pix = cache_mgr.get_thumbnail(vr.video_id)
            title, author = cache_mgr.get_metadata(vr.video_id)
            is_hovered = self._hovered_video_block == vr.start_block
            is_play_hovered = self._hovered_video_play == vr.start_block
            render_video_card(
                painter,
                card_rect,
                vr.video_id,
                pix,
                title=title,
                author=author,
                is_hovered=is_hovered,
                is_play_hovered=is_play_hovered,
                ui_scale=scale,
            )

            if has_sel and (vr.start_block <= sel_end_b and vr.end_block >= sel_start_b):
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(QPen(QColor("#0a84ff"), 1.2))
                painter.setBrush(QBrush(QColor(38, 79, 135, 120)))
                corner_r = round(10.0 * scale, 1)
                painter.drawRoundedRect(card_rect, corner_r, corner_r)
                painter.restore()

        # 5. Render Checkboxes, Inactive Bullets & Inactive Inline Math ($...$)
        # Start strictly from the first visible block in the viewport for O(viewport) performance
        first_cursor = self.cursorForPosition(QPoint(0, 0))
        block = first_cursor.block()
        while block.isValid():
            b_num = block.blockNumber()
            c = QTextCursor(block)
            b_rect = self.cursorRect(c)
            if b_rect.top() > vp_height:
                break

            text = block.text()

            # Horizontal rule (draw clean vector divider line on inactive blocks)
            if HR_RE.match(text):
                if b_rect.bottom() >= 0 and b_num != active_bn:
                    line_y = float(b_rect.top()) + float(b_rect.height()) / 2.0
                    painter.setPen(QPen(QColor("#48484a"), 1.2))
                    painter.drawLine(QPointF(float(b_rect.left()), line_y), QPointF(float(vp_width - 24.0), line_y))

            # Blockquote vertical accent bars (for all quote lines, outside code blocks)
            if block.userState() != 1 and ">" in text:
                qm_bar = QUOTE_RE.match(text)
                if qm_bar:
                    prefix_bar = qm_bar.group(1)
                    level_bar = prefix_bar.count(">")
                    if level_bar > 0:
                        c_s_b = QTextCursor(block)
                        c_e_b = QTextCursor(block)
                        c_e_b.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                        r_s_b = self.cursorRect(c_s_b)
                        r_e_b = self.cursorRect(c_e_b)
                        top_y = float(r_s_b.top())
                        bot_y = float(r_e_b.bottom())

                        if bot_y >= 0 and top_y <= vp_height:
                            painter.save()
                            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                            target_m = level_bar * 18.0 + 8.0
                            base_x = float(r_s_b.left()) - target_m + 4.0
                            for lvl in range(level_bar):
                                bx = base_x + lvl * 18.0
                                next_b = block.next()
                                connects_next = False
                                if next_b.isValid():
                                    next_qm = QUOTE_RE.match(next_b.text())
                                    if next_qm and next_qm.group(1).count(">") > lvl:
                                        connects_next = True

                                pen = QPen(QColor("#545462"), 2.6)
                                if not connects_next:
                                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                                painter.setPen(pen)
                                y2 = bot_y + 1.0 if connects_next else bot_y - 1.0
                                painter.drawLine(QPointF(bx, top_y + 1.0), QPointF(bx, y2))
                            painter.restore()

            # HTML <kbd> Keycaps (inactive lines, outside code blocks)
            if "<kbd>" in text.lower() and b_num != active_bn and block.userState() != 1:
                for km in HTML_KBD_RE.finditer(text):
                    c_s = QTextCursor(block)
                    c_s.setPosition(block.position() + km.start(2))
                    c_e = QTextCursor(block)
                    c_e.setPosition(block.position() + km.end(2))
                    r_s = self.cursorRect(c_s)
                    r_e = self.cursorRect(c_e)
                    if r_s.bottom() >= 0 and r_s.top() <= vp_height:
                        kw = float(r_e.left() - r_s.left())
                        if kw > 0:
                            k_rect = QRectF(float(r_s.left()) - 4.0, float(r_s.top()) + 1.5, kw + 8.0, float(r_s.height()) - 3.0)
                            painter.save()
                            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                            # 3D Bottom shadow edge
                            painter.setPen(QPen(QColor("#18181e"), 1.2))
                            painter.setBrush(QBrush(QColor("#222228")))
                            painter.drawRoundedRect(k_rect, 4.0, 4.0)
                            # Top keycap face
                            top_rect = QRectF(k_rect.left(), k_rect.top(), k_rect.width(), k_rect.height() - 1.8)
                            painter.setPen(QPen(QColor("#545464"), 1.0))
                            painter.setBrush(QBrush(QColor("#2e2e38")))
                            painter.drawRoundedRect(top_rect, 3.5, 3.5)
                            # Key text
                            kf = QFont("Cantarell", -1)
                            kf.setPixelSize(12)
                            kf.setWeight(QFont.Weight.Bold)
                            painter.setFont(kf)
                            painter.setPen(QColor("#f5f5f7"))
                            painter.drawText(top_rect, int(Qt.AlignmentFlag.AlignCenter), km.group(2))
                            painter.restore()

            # Checkbox (never paint inside a code block)
            if block.userState() != 1:
                match = CHECKBOX_PATTERN.match(text)
                if match:
                    indent, full_prefix, status, _ = match.groups()
                    c_cb = QTextCursor(block)
                    c_cb.setPosition(block.position() + len(indent))
                    rect = self.cursorRect(c_cb)
                    if rect.bottom() >= 0:
                        p_start = block.position() + len(indent)
                        p_end = p_start + len(full_prefix)
                        is_sel = has_sel and (p_start < sel_end and p_end > sel_start)
                        if is_sel:
                            c_end = QTextCursor(block)
                            c_end.setPosition(p_end)
                            r_end = self.cursorRect(c_end)
                            prefix_rect = QRectF(float(rect.left()), float(rect.top()), max(0.0, float(r_end.left() - rect.left())), float(rect.height()))
                            painter.fillRect(prefix_rect, sel_bg_color)
                        self._draw_checkbox(painter, rect, status.lower() == "x")
                else:
                    qm = QUOTE_RE.match(text)
                    if qm:
                        prefix_q = qm.group(1)
                        inner_cb = CHECKBOX_PATTERN.match(text[len(prefix_q):])
                        if inner_cb:
                            indent, inner_prefix, status, _ = inner_cb.groups()
                            p_start = block.position() + len(prefix_q) + len(indent)
                            p_end = p_start + len(inner_prefix)
                            is_sel = has_sel and (p_start < sel_end and p_end > sel_start)
                            c_cb = QTextCursor(block)
                            c_cb.setPosition(p_start)
                            rect = self.cursorRect(c_cb)
                            if rect.bottom() >= 0:
                                if is_sel:
                                    c_end = QTextCursor(block)
                                    c_end.setPosition(p_end)
                                    r_end = self.cursorRect(c_end)
                                    prefix_rect = QRectF(float(rect.left()), float(rect.top()), max(0.0, float(r_end.left() - rect.left())), float(rect.height()))
                                    painter.fillRect(prefix_rect, sel_bg_color)
                                self._draw_checkbox(painter, rect, status.lower() == "x")

            # Bullet list item vector rendering (renders when block is inactive OR caret is in content)
            if (
                block.userState() != 1
                and b_num not in self.highlighter._block_modes
            ):
                if not CHECKBOX_PATTERN.match(text):
                    lm = LIST_RE.match(text)
                    if lm:
                        indent, marker, space, _ = lm.groups()
                        if marker in ("-", "*", "+"):
                            prefix_len = len(indent) + len(marker) + len(space)
                            should_draw_bullet = (
                                b_num != active_bn
                                or getattr(self.highlighter, "cursor_pos_in_block", -1) >= prefix_len
                            )
                            if should_draw_bullet:
                                c_bl = QTextCursor(block)
                                c_bl.setPosition(block.position() + len(indent))
                                rect = self.cursorRect(c_bl)
                                if rect.bottom() >= 0:
                                    p_start = block.position() + len(indent)
                                    p_end = p_start + len(marker) + len(space)
                                    is_sel = has_sel and (p_start < sel_end and p_end > sel_start)
                                    if is_sel:
                                        c_end = QTextCursor(block)
                                        c_end.setPosition(p_end)
                                        r_end = self.cursorRect(c_end)
                                        prefix_rect = QRectF(float(rect.left()), float(rect.top()), max(0.0, float(r_end.left() - rect.left())), float(rect.height()))
                                        painter.fillRect(prefix_rect, sel_bg_color)
                                    self._draw_bullet(painter, rect, len(indent))
                    else:
                        qm = QUOTE_RE.match(text)
                        if qm:
                            prefix = qm.group(1)
                            inner_text = text[len(prefix):]
                            if not CHECKBOX_PATTERN.match(inner_text):
                                ilm = LIST_RE.match(inner_text)
                                if ilm:
                                    l_indent, l_marker, l_sp, _ = ilm.groups()
                                    if l_marker in ("-", "*", "+"):
                                        prefix_len = len(prefix) + len(l_indent) + len(l_marker) + len(l_sp)
                                        should_draw_bullet = (
                                            b_num != active_bn
                                            or getattr(self.highlighter, "cursor_pos_in_block", -1) >= prefix_len
                                        )
                                        if should_draw_bullet:
                                            c_bl = QTextCursor(block)
                                            c_bl.setPosition(block.position() + len(prefix) + len(l_indent))
                                            rect = self.cursorRect(c_bl)
                                            if rect.bottom() >= 0:
                                                p_start = block.position() + len(prefix) + len(l_indent)
                                                p_end = p_start + len(l_marker) + len(l_sp)
                                                is_sel = has_sel and (p_start < sel_end and p_end > sel_start)
                                                if is_sel:
                                                    c_end = QTextCursor(block)
                                                    c_end.setPosition(p_end)
                                                    r_end = self.cursorRect(c_end)
                                                    prefix_rect = QRectF(float(rect.left()), float(rect.top()), max(0.0, float(r_end.left() - rect.left())), float(rect.height()))
                                                    painter.fillRect(prefix_rect, sel_bg_color)
                                                self._draw_bullet(painter, rect, len(l_indent))

            # Inline Math on inactive regular blocks (never inside tables or code blocks)
            if (
                self.render_latex
                and b_num != active_bn
                and block.userState() != 1
                and b_num not in self.highlighter._block_modes
                and ("$" in text or "\\(" in text)
            ):
                for m in INLINE_MATH_RE.finditer(text):
                    expr = m.group(1) if m.group(1) is not None else m.group(2)
                    c_m = QTextCursor(block)
                    c_m.setPosition(block.position() + m.start())
                    rect = self.cursorRect(c_m)
                    if rect.bottom() >= 0:
                        pix = render_math_to_pixmap(expr, font_size=15.0, display_mode=False)
                        log_h = pix.height() / pix.devicePixelRatio()
                        py = float(rect.top()) + (rect.height() - log_h) / 2.0
                        painter.drawPixmap(QPointF(float(rect.left()), py), pix)

            block = block.next()

        painter.end()

    def _draw_bullet(self, painter: QPainter, cursor_rect: QRect, indent_len: int) -> None:
        """Draw an Apple Notes-style vector bullet glyph (dot, ring, or square) scaled with ui_scale."""
        scale = getattr(self, "ui_scale", 1.0)
        level = max(0, indent_len // 2)
        cx = float(cursor_rect.left()) + 10.0 * scale
        cy = float(cursor_rect.top()) + float(cursor_rect.height()) / 2.0

        if level == 0:
            # Level 0: Solid circular bullet
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#0a84ff")))
            dot_r = max(1.5, round(3.0 * scale, 1))
            painter.drawEllipse(QPointF(cx, cy), dot_r, dot_r)
        elif level == 1:
            # Level 1: Open ring bullet
            pen = QPen(QColor("#0a84ff"), max(1.0, round(1.6 * scale, 1)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            ring_r = max(1.5, round(2.7 * scale, 1))
            painter.drawEllipse(QPointF(cx, cy), ring_r, ring_r)
        else:
            # Level 2+: Solid square bullet
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#0a84ff")))
            sq = max(2.5, round(4.8 * scale, 1))
            painter.drawRect(QRectF(cx - sq / 2.0, cy - sq / 2.0, sq, sq))

    def _draw_checkbox(self, painter: QPainter, cursor_rect: QRect, is_checked: bool) -> None:
        """Draw a rounded checkbox and vector tick mark scaled with ui_scale."""
        scale = getattr(self, "ui_scale", 1.0)
        box_size = round(14.0 * scale)
        box_x = float(cursor_rect.left()) + round(3.0 * scale)
        box_y = float(cursor_rect.top()) + (cursor_rect.height() - box_size) / 2.0
        box_rect = QRectF(box_x, box_y, box_size, box_size)
        radius = round(3.5 * scale, 1)

        if is_checked:
            painter.setPen(QPen(QColor("#0a84ff"), max(1.0, round(1.5 * scale, 1))))
            painter.setBrush(QBrush(QColor("#0a84ff")))
            painter.drawRoundedRect(box_rect, radius, radius)

            check_pen = QPen(QColor("#ffffff"), max(1.0, round(1.9 * scale, 1)))
            check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            path = QPainterPath()
            path.moveTo(box_x + 3.2 * scale, box_y + 7.2 * scale)
            path.lineTo(box_x + 5.9 * scale, box_y + 9.9 * scale)
            path.lineTo(box_x + 10.8 * scale, box_y + 4.3 * scale)
            painter.drawPath(path)
        else:
            painter.setPen(QPen(QColor("#787880"), max(1.0, round(1.5 * scale, 1))))
            painter.setBrush(QBrush(QColor("#262629")))
            painter.drawRoundedRect(box_rect, radius, radius)

    def _checkbox_block_at_pos(self, pos: QPointF) -> Optional[QTextBlock]:
        """Return the QTextBlock if the viewport position is over a painted checkbox."""
        cursor = self.cursorForPosition(pos.toPoint())
        block = cursor.block()
        if not block.isValid():
            return None

        text = block.text()
        prefix_len = 0
        qm = QUOTE_RE.match(text)
        if qm:
            prefix_len = len(qm.group(1))
            text = text[prefix_len:]

        match = CHECKBOX_PATTERN.match(text)
        if not match:
            return None

        indent, _, _, _ = match.groups()
        c = QTextCursor(block)
        c.setPosition(block.position() + prefix_len + len(indent))
        rect = self.cursorRect(c)
        scale = getattr(self, "ui_scale", 1.0)
        box_size = round(14.0 * scale)
        box_x = float(rect.left()) + round(3.0 * scale)
        box_y = float(rect.top()) + (rect.height() - box_size) / 2.0
        min_x = max(0.0, box_x - 8.0 * scale)
        max_x = box_x + box_size + 8.0 * scale
        min_y = box_y - 6.0 * scale
        max_y = box_y + box_size + 6.0 * scale

        if min_x <= pos.x() <= max_x and min_y <= pos.y() <= max_y:
            return block
        return None

    def _region_at_pos(self, pos: QPointF) -> Optional[tuple[int, int, QRectF]]:
        """Return the rendered preview card (start_block, end_block, rect) if clicked/hovered."""
        for s_blk, e_blk, r in self._rendered_block_rects:
            if r.contains(pos):
                return s_blk, e_blk, r
        return None

    def _link_at_pos(self, pos: QPointF | QPoint) -> Optional[tuple[int, int, str]]:
        """Return (start, end, url) if viewport position is over a Markdown link."""
        pt = pos.toPoint() if hasattr(pos, "toPoint") else pos
        cursor = self.cursorForPosition(pt)
        block = cursor.block()
        if not block.isValid():
            return None
        offset = cursor.positionInBlock()
        return find_link_at_offset(block.text(), offset)

    def _open_url(self, url: str) -> None:
        """Open a URL in the user's default web browser."""
        clean_url = url.strip()
        if not (
            clean_url.startswith("http://")
            or clean_url.startswith("https://")
            or clean_url.startswith("mailto:")
            or clean_url.startswith("file://")
        ):
            clean_url = "https://" + clean_url
        QDesktopServices.openUrl(QUrl(clean_url))

    def _find_hscroll_target(self, pos: QPointF) -> Optional[tuple[str, int, float]]:
        """Find if pos is within an inactive table or code card that has horizontal overflow."""
        active_bn = self.highlighter.active_block_number
        for tr in self.highlighter.table_regions:
            if not (tr.start_block <= active_bn <= tr.end_block):
                tbl_rect = self._get_table_rect(tr)
                if tbl_rect is not None and tbl_rect.contains(pos):
                    content_w, _ = get_table_column_widths(tr, self.font(), tbl_rect.width())
                    max_s = max(0.0, content_w - tbl_rect.width())
                    if max_s > 0:
                        return ("table", tr.start_block, max_s)
        for cr in self.highlighter.code_regions:
            if not (cr.start_block <= active_bn <= cr.end_block):
                card_rect = self._get_code_card_rect(cr)
                if card_rect is not None and card_rect.contains(pos):
                    scale = getattr(self, "ui_scale", 1.0)
                    content_w = get_code_content_width(cr, ui_scale=scale)
                    gutter_w = get_code_gutter_width(cr, ui_scale=scale) if self.code_line_numbers else 0.0
                    max_s = max(0.0, content_w - (card_rect.width() - gutter_w))
                    if max_s > 0:
                        return ("code", cr.start_block, max_s)
        return None

    def _on_touch_down(self, pos: QPointF) -> None:
        """Handle touchscreen press / contact begin."""
        self._kinetic_timer.stop()
        self._kinetic_vx = 0.0
        self._kinetic_vy = 0.0
        target = self._find_hscroll_target(pos)
        self._touch_tracker.start(pos, time.time(), target)

    def _on_touch_move(self, pos: QPointF) -> None:
        """Handle touchscreen drag / move."""
        dx, dy, is_scrolling = self._touch_tracker.update(pos, time.time())
        if is_scrolling:
            # Prevent text selection on touchscreen drag
            c = self.textCursor()
            if c.hasSelection():
                c.clearSelection()
                self.setTextCursor(c)

            # 1. Vertical scroll
            if dy != 0:
                vsb = self.verticalScrollBar()
                vsb.setValue(int(vsb.value() - dy))

            # 2. Horizontal scroll
            target = self._touch_tracker.target_region
            if target is not None:
                kind, blk_id, max_s = target
                if kind == "table":
                    cur_s = self._table_scroll_x.get(blk_id, 0.0)
                    new_s = max(0.0, min(max_s, cur_s - dx))
                    if new_s != cur_s:
                        self._table_scroll_x[blk_id] = new_s
                        self.viewport().update()
                elif kind == "code":
                    cur_s = self._code_scroll_x.get(blk_id, 0.0)
                    new_s = max(0.0, min(max_s, cur_s - dx))
                    if new_s != cur_s:
                        self._code_scroll_x[blk_id] = new_s
                        self.viewport().update()
            else:
                hsb = self.horizontalScrollBar()
                if hsb.maximum() > 0 and dx != 0:
                    hsb.setValue(int(hsb.value() - dx))

    def _on_touch_up(self, pos: QPointF) -> None:
        """Handle touchscreen release / contact end."""
        target = self._touch_tracker.target_region
        was_scrolling, vx, vy = self._touch_tracker.end(time.time())
        if was_scrolling:
            if abs(vy) > 0.8 or abs(vx) > 0.8:
                self._kinetic_vx = vx
                self._kinetic_vy = vy
                self._kinetic_target = target
                self._kinetic_timer.start(16)
        else:
            self._handle_touch_tap(pos)

    def _on_kinetic_tick(self) -> None:
        """Smooth momentum deceleration tick."""
        if abs(self._kinetic_vy) > 0.4:
            vsb = self.verticalScrollBar()
            vsb.setValue(int(vsb.value() - self._kinetic_vy))
            self._kinetic_vy *= 0.92
        else:
            self._kinetic_vy = 0.0

        if abs(self._kinetic_vx) > 0.4 and self._kinetic_target is not None:
            kind, blk_id, max_s = self._kinetic_target
            if kind == "table":
                cur_s = self._table_scroll_x.get(blk_id, 0.0)
                new_s = max(0.0, min(max_s, cur_s - self._kinetic_vx))
                self._table_scroll_x[blk_id] = new_s
                self.viewport().update()
            elif kind == "code":
                cur_s = self._code_scroll_x.get(blk_id, 0.0)
                new_s = max(0.0, min(max_s, cur_s - self._kinetic_vx))
                self._code_scroll_x[blk_id] = new_s
                self.viewport().update()
            self._kinetic_vx *= 0.92
        else:
            self._kinetic_vx = 0.0

        if abs(self._kinetic_vy) <= 0.4 and abs(self._kinetic_vx) <= 0.4:
            self._kinetic_timer.stop()

    def _handle_touch_tap(self, pos: QPointF) -> None:
        """Process a clean tap or double-tap on touchscreen without drag."""
        now = time.time()
        is_double_tap = (
            (now - self._last_tap_time <= 0.35)
            and (math.hypot(pos.x() - self._last_tap_pos.x(), pos.y() - self._last_tap_pos.y()) < 24.0)
        )
        self._last_tap_time = now
        self._last_tap_pos = pos

        if is_double_tap:
            reg = self._region_at_pos(pos)
            if reg is not None:
                s_blk, _, _ = reg
                target_block = self.document().findBlockByNumber(s_blk + 1)
                if not target_block.isValid():
                    target_block = self.document().findBlockByNumber(s_blk)
                if target_block.isValid():
                    c = QTextCursor(target_block)
                    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                    self.setTextCursor(c)
                    self.ensureCursorVisible()
                    self.viewport().update()
                    return
            else:
                c = self.cursorForPosition(pos.toPoint())
                c.select(QTextCursor.SelectionType.WordUnderCursor)
                self.setTextCursor(c)
                return

        # Single Tap Actions:
        active_bn = self.highlighter.active_block_number
        scale = getattr(self, "ui_scale", 1.0)

        # 1. Check Copy button
        for cr in self.highlighter.code_regions:
            if not (cr.start_block <= active_bn <= cr.end_block):
                card_rect = self._get_code_card_rect(cr)
                if card_rect is not None and card_rect.contains(pos):
                    btn_rect = get_code_copy_button_rect(card_rect, ui_scale=scale)
                    if btn_rect.contains(pos):
                        code_text = "\n".join(cr.lines)
                        QApplication.clipboard().setText(code_text)
                        self._copied_code_block = cr.start_block
                        self._copied_timer.start(2000)
                        self.viewport().update()
                        return

        # 2. Check Edit button
        for cr in self.highlighter.code_regions:
            if not (cr.start_block <= active_bn <= cr.end_block):
                card_rect = self._get_code_card_rect(cr)
                if card_rect is not None and card_rect.contains(pos):
                    edit_btn = get_code_edit_button_rect(card_rect, ui_scale=scale)
                    if edit_btn.contains(pos):
                        target_block = self.document().findBlockByNumber(cr.start_block + 1)
                        if not target_block.isValid():
                            target_block = self.document().findBlockByNumber(cr.start_block)
                        if target_block.isValid():
                            c = QTextCursor(target_block)
                            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                            self.setTextCursor(c)
                            self.ensureCursorVisible()
                            self.viewport().update()
                            return

        # 3. Checkbox tap
        block = self._checkbox_block_at_pos(pos)
        if block is not None:
            self._toggle_checkbox_at_block(block)
            return

        # 4. Inactive preview card tap -> do nothing (keeps card intact)
        if self._region_at_pos(pos) is not None:
            return

        # 5. Normal text tap -> position cursor cleanly with no selection
        c = self.cursorForPosition(pos.toPoint())
        c.clearSelection()
        self.setTextCursor(c)
        self.ensureCursorVisible()

    def viewportEvent(self, event: QEvent) -> bool:
        """Handle touchscreen gestures natively without triggering text selection."""
        t = event.type()
        if t in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            if isinstance(event, QTouchEvent) and event.points():
                pt = event.points()[0]
                pos = pt.position()
                if t == QEvent.Type.TouchBegin:
                    self._on_touch_down(pos)
                elif t == QEvent.Type.TouchUpdate:
                    self._on_touch_move(pos)
                elif t in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
                    self._on_touch_up(pos)
                event.accept()
                return True
        return super().viewportEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Show pointer cursor on interactive elements and handle scrollbar dragging."""
        if is_touch_event(event):
            if self._touch_tracker.is_active:
                self._on_touch_move(event.position())
            return
        elif self._touch_tracker.is_active:
            self._touch_tracker.reset()

        super().mouseMoveEvent(event)
        pos = event.position()
        active_bn = self.highlighter.active_block_number

        # Handle active scrollbar dragging
        if self._scrollbar_drag is not None:
            kind, block_id, start_x, start_s, max_s, track_w, thumb_w = self._scrollbar_drag
            scroll_range = max(1.0, track_w - thumb_w)
            dx = pos.x() - start_x
            new_s = max(0.0, min(max_s, start_s + (dx / scroll_range) * max_s))
            if kind == "table":
                self._table_scroll_x[block_id] = new_s
            else:
                self._code_scroll_x[block_id] = new_s
            self.viewport().update()
            return

        # Check if hovering over Code Copy button
        scale = getattr(self, "ui_scale", 1.0)
        old_hovered_copy = self._hovered_copy_btn
        self._hovered_copy_btn = None
        for cr in self.highlighter.code_regions:
            if not (cr.start_block <= active_bn <= cr.end_block):
                card_rect = self._get_code_card_rect(cr)
                if card_rect is not None and card_rect.contains(pos):
                    btn_rect = get_code_copy_button_rect(card_rect, ui_scale=scale)
                    if btn_rect.contains(pos):
                        self._hovered_copy_btn = cr.start_block
                        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                        tip = "Copied!" if self._copied_code_block == cr.start_block else "Copy code to clipboard"
                        QToolTip.showText(event.globalPosition().toPoint(), tip, self.viewport())
                        if old_hovered_copy != self._hovered_copy_btn:
                            self.viewport().update()
                        return

        if old_hovered_copy is not None:
            self.viewport().update()

        # Check if hovering over Code Edit button
        old_hovered_edit = self._hovered_edit_btn
        self._hovered_edit_btn = None
        for cr in self.highlighter.code_regions:
            if not (cr.start_block <= active_bn <= cr.end_block):
                card_rect = self._get_code_card_rect(cr)
                if card_rect is not None and card_rect.contains(pos):
                    edit_btn = get_code_edit_button_rect(card_rect, ui_scale=scale)
                    if edit_btn.contains(pos):
                        self._hovered_edit_btn = cr.start_block
                        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                        QToolTip.showText(event.globalPosition().toPoint(), "Edit code block", self.viewport())
                        if old_hovered_edit != self._hovered_edit_btn:
                            self.viewport().update()
                        return

        if old_hovered_edit is not None:
            self.viewport().update()

        # Check if hovering over table scrollbar
        for tr in self.highlighter.table_regions:
            if not (tr.start_block <= active_bn <= tr.end_block):
                tbl_rect = self._get_table_rect(tr)
                if tbl_rect is not None and tbl_rect.contains(pos):
                    content_w, _ = get_table_column_widths(tr, self.font(), tbl_rect.width())
                    cur_s = self._table_scroll_x.get(tr.start_block, 0.0)
                    sb = get_table_scrollbar_geometry(tbl_rect, content_w, cur_s)
                    if sb is not None and sb[0].contains(pos):
                        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                        QToolTip.hideText()
                        return

        # Check if hovering over code scrollbar
        for cr in self.highlighter.code_regions:
            if not (cr.start_block <= active_bn <= cr.end_block):
                card_rect = self._get_code_card_rect(cr)
                if card_rect is not None and card_rect.contains(pos):
                    content_w = get_code_content_width(cr, ui_scale=scale)
                    cur_s = self._code_scroll_x.get(cr.start_block, 0.0)
                    gutter_w = get_code_gutter_width(cr, ui_scale=scale) if self.code_line_numbers else 0.0
                    sb = get_code_scrollbar_geometry(card_rect, content_w, cur_s, gutter_width=gutter_w, ui_scale=scale)
                    if sb is not None and sb[0].contains(pos):
                        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
                        QToolTip.hideText()
                        return

        # Checkboxes
        if self._checkbox_block_at_pos(pos) is not None:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.hideText()
            return

        # Inactive date card hover
        hovered_date: Optional[int] = None
        for b_num, (card_r, _) in self._date_card_rects.items():
            if card_r.contains(pos):
                hovered_date = b_num
                break
        if hovered_date != self._hovered_date_block:
            self._hovered_date_block = hovered_date
            self.viewport().update()

        if hovered_date is not None:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.showText(
                event.globalPosition().toPoint(),
                "Click to edit date",
                self.viewport(),
            )
            return

        # Inactive YouTube video card hover
        hovered_video: Optional[int] = None
        hovered_video_play: Optional[int] = None
        for b_num, (v_rect, vr) in self._video_card_rects.items():
            if v_rect.contains(pos):
                hovered_video = b_num
                info_h = round(46.0 * scale)
                thumb_h = max(20.0, v_rect.height() - info_h)
                btn_w = round(64.0 * scale)
                btn_h = round(44.0 * scale)
                btn_x = v_rect.left() + (v_rect.width() - btn_w) / 2.0
                btn_y = v_rect.top() + (thumb_h - btn_h) / 2.0
                play_rect = QRectF(btn_x, btn_y, btn_w, btn_h)
                if play_rect.contains(pos):
                    hovered_video_play = b_num
                break

        if hovered_video != self._hovered_video_block or hovered_video_play != self._hovered_video_play:
            self._hovered_video_block = hovered_video
            self._hovered_video_play = hovered_video_play
            self.viewport().update()

        if hovered_video is not None:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            _, vr = self._video_card_rects[hovered_video]
            title, author = YouTubeCacheManager.instance().get_metadata(vr.video_id)
            label = f"{title} - {author}" if author else title
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"Click to watch: {label}\nDouble-click to edit source",
                self.viewport(),
            )
            return

        # Inactive preview card hover
        if self._region_at_pos(pos) is not None:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.hideText()
            return

        link_info = self._link_at_pos(pos)
        if link_info is not None:
            _, _, url = link_info
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"Ctrl+Click to open {url}",
                self.viewport(),
            )
            return

        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        QToolTip.hideText()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle clicking directly on checkboxes, buttons, scrollbars, or Ctrl+Click on links."""
        if self.slash_palette.isVisible():
            self.slash_palette.hide()
        if hasattr(self, "format_toolbar") and self.format_toolbar.isVisible():
            self.format_toolbar.hide()

        if is_touch_event(event):
            self._on_touch_down(event.position())
            return
        elif self._touch_tracker.is_active:
            self._touch_tracker.reset()

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            active_bn = self.highlighter.active_block_number

            # 0. Ctrl+Click on link -> open in browser
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                link_info = self._link_at_pos(pos)
                if link_info is not None:
                    _, _, url = link_info
                    self._open_url(url)
                    return

            # 1. Click on Code Card Copy button
            scale = getattr(self, "ui_scale", 1.0)
            for cr in self.highlighter.code_regions:
                if not (cr.start_block <= active_bn <= cr.end_block):
                    card_rect = self._get_code_card_rect(cr)
                    if card_rect is not None and card_rect.contains(pos):
                        btn_rect = get_code_copy_button_rect(card_rect, ui_scale=scale)
                        if btn_rect.contains(pos):
                            code_text = "\n".join(cr.lines)
                            QApplication.clipboard().setText(code_text)
                            self._copied_code_block = cr.start_block
                            self._copied_timer.start(2000)
                            self.viewport().update()
                            return

            # 2. Click on Code Card Edit button
            for cr in self.highlighter.code_regions:
                if not (cr.start_block <= active_bn <= cr.end_block):
                    card_rect = self._get_code_card_rect(cr)
                    if card_rect is not None and card_rect.contains(pos):
                        edit_btn = get_code_edit_button_rect(card_rect, ui_scale=scale)
                        if edit_btn.contains(pos):
                            target_block = self.document().findBlockByNumber(cr.start_block + 1)
                            if not target_block.isValid():
                                target_block = self.document().findBlockByNumber(cr.start_block)
                            if target_block.isValid():
                                c = QTextCursor(target_block)
                                c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                                self.setTextCursor(c)
                                self.ensureCursorVisible()
                                self.viewport().update()
                                return

            # 3. Click on Code Card Scrollbar
            for cr in self.highlighter.code_regions:
                if not (cr.start_block <= active_bn <= cr.end_block):
                    card_rect = self._get_code_card_rect(cr)
                    if card_rect is not None:
                        content_w = get_code_content_width(cr, ui_scale=scale)
                        cur_s = self._code_scroll_x.get(cr.start_block, 0.0)
                        gutter_w = get_code_gutter_width(cr, ui_scale=scale) if self.code_line_numbers else 0.0
                        sb = get_code_scrollbar_geometry(card_rect, content_w, cur_s, gutter_width=gutter_w, ui_scale=scale)
                        if sb is not None:
                            track_r, thumb_r, max_s = sb
                            if track_r.contains(pos):
                                if not thumb_r.contains(pos):
                                    ratio = (pos.x() - track_r.left()) / max(1.0, track_r.width())
                                    cur_s = max(0.0, min(max_s, ratio * max_s))
                                    self._code_scroll_x[cr.start_block] = cur_s
                                self._scrollbar_drag = ("code", cr.start_block, pos.x(), cur_s, max_s, track_r.width(), thumb_r.width())
                                self.viewport().update()
                                return
                            elif thumb_r.contains(pos):
                                self._scrollbar_drag = ("code", cr.start_block, pos.x(), cur_s, max_s, track_r.width(), thumb_r.width())
                                return

            # 4. Click on Table Scrollbar
            for tr in self.highlighter.table_regions:
                if not (tr.start_block <= active_bn <= tr.end_block):
                    tbl_rect = self._get_table_rect(tr)
                    if tbl_rect is not None:
                        content_w, _ = get_table_column_widths(tr, self.font(), tbl_rect.width())
                        cur_s = self._table_scroll_x.get(tr.start_block, 0.0)
                        sb = get_table_scrollbar_geometry(tbl_rect, content_w, cur_s)
                        if sb is not None:
                            track_r, thumb_r, max_s = sb
                            if track_r.contains(pos):
                                if not thumb_r.contains(pos):
                                    ratio = (pos.x() - track_r.left()) / max(1.0, track_r.width())
                                    cur_s = max(0.0, min(max_s, ratio * max_s))
                                    self._table_scroll_x[tr.start_block] = cur_s
                                self._scrollbar_drag = ("table", tr.start_block, pos.x(), cur_s, max_s, track_r.width(), thumb_r.width())
                                self.viewport().update()
                                return
                            elif thumb_r.contains(pos):
                                self._scrollbar_drag = ("table", tr.start_block, pos.x(), cur_s, max_s, track_r.width(), thumb_r.width())
                                return

            # 5. Checkbox click -> toggle
            block = self._checkbox_block_at_pos(pos)
            if block is not None:
                self._toggle_checkbox_at_block(block)
                return

            # 5.5 Click on Date Card -> open ModernDatePickerDialog
            for b_num, (card_rect, target_date) in list(self._date_card_rects.items()):
                if card_rect.contains(pos):
                    dlg = ModernDatePickerDialog(parent=self, initial_date=target_date)
                    if dlg.exec():
                        new_date = dlg.selected_date
                        b = self.document().findBlockByNumber(b_num)
                        if b.isValid():
                            c = QTextCursor(b)
                            c.beginEditBlock()
                            c.select(QTextCursor.SelectionType.LineUnderCursor)
                            c.insertText(f"@date({new_date.isoformat()})")
                            c.endEditBlock()
                            self.viewport().update()
                    return

            # 5.6 Click on YouTube Video Card -> open URL in browser
            for b_num, (v_rect, vr) in list(self._video_card_rects.items()):
                if v_rect.contains(pos):
                    self._open_url(vr.url)
                    return

            # Single click on rendered card does NOT blow up the card; double-click is required
            if self._region_at_pos(pos) is not None:
                return

        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Double-click on any rendered card to enter inline Markdown editing."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            reg = self._region_at_pos(pos)
            if reg is not None:
                s_blk, _, _ = reg
                target_block = self.document().findBlockByNumber(s_blk + 1)
                if not target_block.isValid():
                    target_block = self.document().findBlockByNumber(s_blk)
                if target_block.isValid():
                    c = QTextCursor(target_block)
                    c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                    self.setTextCursor(c)
                    self.ensureCursorVisible()
                    self.viewport().update()
                    return

        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish any active scrollbar dragging or touch scrolling."""
        if is_touch_event(event):
            self._on_touch_up(event.position())
            return
        elif self._touch_tracker.is_active:
            self._touch_tracker.reset()

        self._scrollbar_drag = None
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        """Clear button and card hover states when the cursor leaves the editor."""
        if self._hovered_date_block is not None:
            self._hovered_date_block = None
            self.viewport().update()
        if self._hovered_video_block is not None or self._hovered_video_play is not None:
            self._hovered_video_block = None
            self._hovered_video_play = None
            self.viewport().update()
        if self._hovered_copy_btn is not None or self._hovered_edit_btn is not None:
            self._hovered_copy_btn = None
            self._hovered_edit_btn = None
            self.viewport().update()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Handle horizontal scrolling on tables and code blocks with trackpad or Shift+Wheel, and Ctrl+Wheel zooming."""
        if self.slash_palette.isVisible():
            self.slash_palette.hide()
        if hasattr(self, "format_toolbar") and self.format_toolbar.isVisible():
            self.format_toolbar.hide()

        # Ctrl+MouseWheel: Zoom In / Zoom Out
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta_y = event.angleDelta().y()
            if delta_y > 0:
                self.zoom_in_requested.emit()
            elif delta_y < 0:
                self.zoom_out_requested.emit()
            event.accept()
            return

        pos = event.position()
        delta_x = event.angleDelta().x()
        if delta_x == 0 and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            delta_x = event.angleDelta().y()

        active_bn = self.highlighter.active_block_number

        if delta_x != 0:
            # 1. Check if hovering over an inactive table
            for tr in self.highlighter.table_regions:
                if tr.start_block <= active_bn <= tr.end_block:
                    continue
                tbl_rect = self._get_table_rect(tr)
                if tbl_rect is not None and tbl_rect.contains(pos):
                    content_w, _ = get_table_column_widths(tr, self.font(), tbl_rect.width())
                    max_s = max(0.0, content_w - tbl_rect.width())
                    if max_s > 0:
                        cur_s = self._table_scroll_x.get(tr.start_block, 0.0)
                        new_s = max(0.0, min(max_s, cur_s - delta_x * 0.8))
                        if new_s != cur_s:
                            self._table_scroll_x[tr.start_block] = new_s
                            self.viewport().update()
                        event.accept()
                        return

            # 2. Check if hovering over an inactive code card
            scale = getattr(self, "ui_scale", 1.0)
            for cr in self.highlighter.code_regions:
                if cr.start_block <= active_bn <= cr.end_block:
                    continue
                card_rect = self._get_code_card_rect(cr)
                if card_rect is not None and card_rect.contains(pos):
                    content_w = get_code_content_width(cr, ui_scale=scale)
                    gutter_w = get_code_gutter_width(cr, ui_scale=scale) if self.code_line_numbers else 0.0
                    max_s = max(0.0, content_w - (card_rect.width() - gutter_w))
                    if max_s > 0:
                        cur_s = self._code_scroll_x.get(cr.start_block, 0.0)
                        new_s = max(0.0, min(max_s, cur_s - delta_x * 0.8))
                        if new_s != cur_s:
                            self._code_scroll_x[cr.start_block] = new_s
                            self.viewport().update()
                        event.accept()
                        return

        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle Escape exit, Ctrl+Enter toggling, smart list continuation, and Tab indentation."""
        # Dismiss format toolbar on keypress
        if hasattr(self, "format_toolbar") and self.format_toolbar.isVisible():
            if event.key() == Qt.Key.Key_Escape:
                self.format_toolbar.hide()
                event.accept()
                return
            self.format_toolbar.hide()

        # 0. Intercept Slash Command Palette navigation and execution when open
        if self.slash_palette.isVisible():
            if event.key() == Qt.Key.Key_Escape:
                self.slash_palette.hide()
                event.accept()
                return

            if event.key() == Qt.Key.Key_Down:
                self.slash_palette.select_next()
                event.accept()
                return

            if event.key() == Qt.Key.Key_Up:
                self.slash_palette.select_previous()
                event.accept()
                return

            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                self.slash_palette.execute_current()
                event.accept()
                return

            if event.key() == Qt.Key.Key_Backspace:
                super().keyPressEvent(event)
                cur_pos = self.textCursor().position()
                if self._slash_start_pos is None or cur_pos < self._slash_start_pos - 1:
                    self.slash_palette.hide()
                else:
                    if cur_pos < self._slash_start_pos:
                        self.slash_palette.populate("")
                    else:
                        query = self.document().toPlainText()[self._slash_start_pos:cur_pos]
                        self.slash_palette.populate(query)
                return

            if event.key() in (
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Home,
                Qt.Key.Key_End,
                Qt.Key.Key_PageUp,
                Qt.Key.Key_PageDown,
            ):
                self.slash_palette.hide()
                super().keyPressEvent(event)
                return

            if event.text() and event.text().isprintable():
                if event.text() == " ":
                    self.slash_palette.hide()
                    super().keyPressEvent(event)
                    return
                super().keyPressEvent(event)
                cur_pos = self.textCursor().position()
                if self._slash_start_pos is not None and cur_pos >= self._slash_start_pos:
                    query = self.document().toPlainText()[self._slash_start_pos:cur_pos]
                    if "\n" in query:
                        self.slash_palette.hide()
                    else:
                        self.slash_palette.populate(query)
                        if self.slash_palette.count() == 0:
                            self.slash_palette.hide()
                return

        cursor = self.textCursor()
        block = cursor.block()
        line_text = block.text()
        pos_in_block = cursor.positionInBlock()

        # F1 opens shortcuts reference cheatsheet
        if event.key() == Qt.Key.Key_F1:
            self._show_shortcuts_dialog()
            event.accept()
            return

        mods = event.modifiers()
        has_ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        has_shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        has_alt = bool(mods & Qt.KeyboardModifier.AltModifier)

        # Alt-based productivity shortcuts
        if has_alt and not has_ctrl:
            # Alt+W: Toggle Word Wrap
            if event.key() == Qt.Key.Key_W or event.text().lower() == "w":
                self.toggle_word_wrap()
                event.accept()
                return

        # Standard Undo / Redo shortcuts (handled via PlainTextUndoManager)
        if event.matches(QKeySequence.StandardKey.Undo) or (
            has_ctrl and not has_alt and not has_shift and event.key() == Qt.Key.Key_Z
        ):
            if self.slash_palette.isVisible():
                self.slash_palette.hide()
            self.undo()
            event.accept()
            return

        if event.matches(QKeySequence.StandardKey.Redo) or (
            has_ctrl
            and not has_alt
            and (
                (not has_shift and event.key() == Qt.Key.Key_Y)
                or (has_shift and event.key() == Qt.Key.Key_Z)
            )
        ):
            if self.slash_palette.isVisible():
                self.slash_palette.hide()
            self.redo()
            event.accept()
            return

        # Ctrl-based productivity and markdown formatting shortcuts
        if has_ctrl and not has_alt:
            # Ctrl++ or Ctrl+= zooms in
            if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal) or event.text() in ("+", "="):
                self.zoom_in_requested.emit()
                event.accept()
                return

            # Ctrl+- or Ctrl+_ zooms out
            if event.key() in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore) or event.text() in ("-", "_"):
                self.zoom_out_requested.emit()
                event.accept()
                return

            # Ctrl+0 resets zoom
            if event.key() == Qt.Key.Key_0 or event.text() == "0":
                self.zoom_reset_requested.emit()
                event.accept()
                return

            # Ctrl+, opens settings modal
            if event.key() in (Qt.Key.Key_Comma, Qt.Key.Key_Less) or event.text() in (",", "<"):
                self.settings_requested.emit()
                event.accept()
                return

            # Ctrl+/ or Ctrl+? opens shortcuts modal
            if event.key() in (Qt.Key.Key_Slash, Qt.Key.Key_Question) or event.text() in ("/", "?"):
                self._show_shortcuts_dialog()
                event.accept()
                return

            if not has_shift:
                if event.key() == Qt.Key.Key_F:
                    self.find_requested.emit(False)
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_H:
                    self.find_requested.emit(True)
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_K:
                    self._apply_text_format("link")
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_B:
                    self._apply_text_format("bold")
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_I:
                    self._apply_text_format("italic")
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_U:
                    self._apply_text_format("underline")
                    event.accept()
                    return
                elif event.key() in (Qt.Key.Key_1, Qt.Key.Key_Exclam):
                    self._apply_block_heading(1)
                    event.accept()
                    return
                elif event.key() in (Qt.Key.Key_2, Qt.Key.Key_At):
                    self._apply_block_heading(2)
                    event.accept()
                    return
                elif event.key() in (Qt.Key.Key_3, Qt.Key.Key_NumberSign):
                    self._apply_block_heading(3)
                    event.accept()
                    return
            else:
                # Ctrl + Shift + ...
                if event.key() == Qt.Key.Key_X:
                    self._apply_text_format("strike")
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_C:
                    self._apply_text_format("code")
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_K:
                    self._apply_code_block()
                    event.accept()
                    return
                elif event.key() in (Qt.Key.Key_U, Qt.Key.Key_7, Qt.Key.Key_Ampersand):
                    self._apply_text_format("bullet")
                    event.accept()
                    return
                elif event.key() in (Qt.Key.Key_O, Qt.Key.Key_8, Qt.Key.Key_Asterisk):
                    self._apply_text_format("number")
                    event.accept()
                    return
                elif event.key() in (Qt.Key.Key_T, Qt.Key.Key_L):
                    self._apply_text_format("todo")
                    event.accept()
                    return
                elif event.key() == Qt.Key.Key_Q:
                    self._apply_blockquote()
                    event.accept()
                    return

        # Up arrow at the very top of document: jump up to NoteTitleEdit
        if event.key() == Qt.Key.Key_Up:
            if block.blockNumber() == 0 and pos_in_block == 0 and not (event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)):
                self.up_at_top_requested.emit()
                event.accept()
                return

        # Open Slash Command Palette on typing '/' at start of line or after space
        if event.text() == "/" and not (
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            is_valid_trigger = (
                pos_in_block == 0
                or line_text[:pos_in_block].isspace()
                or (pos_in_block > 0 and line_text[pos_in_block - 1] == " ")
            )
            if is_valid_trigger:
                super().keyPressEvent(event)
                self._slash_start_pos = self.textCursor().position()
                self._show_slash_palette()
                return

        # Escape key: dismiss active find bar, popups, or exit active card editing mode
        if event.key() == Qt.Key.Key_Escape:
            if self.format_toolbar.isVisible():
                self.format_toolbar.hide()
                return
            if self.slash_palette.isVisible():
                self.slash_palette.hide()
                return
            if self._search_matches:
                self.find_close_requested.emit()
                return
            b_num = block.blockNumber()
            for r_list in (
                self.highlighter.code_regions,
                self.highlighter.table_regions,
                self.highlighter.math_regions,
                self.highlighter.mermaid_regions,
            ):
                for r in r_list:
                    if r.start_block <= b_num <= r.end_block:
                        next_b = self.document().findBlockByNumber(r.end_block + 1)
                        if not next_b.isValid():
                            next_b = self.document().findBlockByNumber(r.start_block - 1)
                        if next_b.isValid():
                            c = QTextCursor(next_b)
                            c.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                            self.setTextCursor(c)
                            self.ensureCursorVisible()
                            self.viewport().update()
                            return

        # Check if inside a table row
        if is_table_row(line_text):
            # Tab inside table: advance to next cell (or create new row if at end)
            if event.key() == Qt.Key.Key_Tab and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                next_pos = find_next_cell_pos(line_text, pos_in_block)
                if next_pos is not None:
                    c = QTextCursor(block)
                    c.setPosition(block.position() + next_pos)
                    self.setTextCursor(c)
                else:
                    next_b = block.next()
                    if next_b.isValid() and is_table_row(next_b.text()):
                        if is_table_separator(next_b.text()):
                            next_b = next_b.next()
                        if next_b.isValid() and is_table_row(next_b.text()):
                            fp = find_next_cell_pos(next_b.text(), 0)
                            c = QTextCursor(next_b)
                            c.setPosition(next_b.position() + (fp or 2))
                            self.setTextCursor(c)
                    else:
                        num_cols = len(split_table_cells(line_text))
                        cursor.beginEditBlock()
                        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                        cursor.insertText("\n" + create_empty_table_row(num_cols))
                        cursor.endEditBlock()
                        new_b = self.textCursor().block()
                        fp = find_next_cell_pos(new_b.text(), 0)
                        c = QTextCursor(new_b)
                        c.setPosition(new_b.position() + (fp or 2))
                        self.setTextCursor(c)
                return

            # Shift+Tab inside table: go to previous cell
            if event.key() == Qt.Key.Key_Tab and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                prev_pos = find_prev_cell_pos(line_text, pos_in_block)
                if prev_pos is not None:
                    c = QTextCursor(block)
                    c.setPosition(block.position() + prev_pos)
                    self.setTextCursor(c)
                else:
                    prev_b = block.previous()
                    if prev_b.isValid() and is_table_separator(prev_b.text()):
                        prev_b = prev_b.previous()
                    if prev_b.isValid() and is_table_row(prev_b.text()):
                        pipes = [m.start() for m in re.finditer(r"\|", prev_b.text())]
                        if len(pipes) >= 2:
                            c = QTextCursor(prev_b)
                            c.setPosition(prev_b.position() + pipes[-2] + 2)
                            self.setTextCursor(c)
                return

            # Enter inside table: smart row continuation or exit
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
            ):
                if is_empty_table_row(line_text):
                    # Exit table: remove current empty row
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                    cursor.endEditBlock()
                    self.viewport().update()
                    return
                else:
                    num_cols = len(split_table_cells(line_text))
                    prev_b = block.previous()
                    is_first_header = not (prev_b.isValid() and is_table_row(prev_b.text()))
                    cursor.beginEditBlock()
                    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
                    if is_first_header:
                        sep = "|" + "|".join("---" for _ in range(num_cols)) + "|"
                        cursor.insertText("\n" + sep + "\n" + create_empty_table_row(num_cols))
                    else:
                        cursor.insertText("\n" + create_empty_table_row(num_cols))
                    cursor.endEditBlock()
                    new_b = self.textCursor().block()
                    fp = find_next_cell_pos(new_b.text(), 0)
                    c = QTextCursor(new_b)
                    c.setPosition(new_b.position() + (fp or 2))
                    self.setTextCursor(c)
                    self.ensureCursorVisible()
                    self.viewport().update()
                    return

        # 0. Auto-expand "- []" into "- [ ]" when the user types closing bracket "]"
        if event.text() == "]" and re.match(r"^\s*[-*+]\s*\[$", line_text[:pos_in_block]):
            cursor.beginEditBlock()
            cursor.insertText(" ]")
            cursor.endEditBlock()
            self.viewport().update()
            return

        # Atomically skip cursor across hidden HTML color/mark tags
        if not cursor.hasSelection() and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)):
                if "<" in line_text or "mark" in line_text or "span" in line_text:
                    if event.key() == Qt.Key.Key_Right:
                        for tm in re.finditer(r"<{0,1}(?:mark|span|u|/mark|/span|/u)[^>]*>", line_text, re.IGNORECASE):
                            ts, te = tm.span()
                            if pos_in_block == ts:
                                new_c = QTextCursor(cursor)
                                new_c.setPosition(block.position() + te)
                                self.setTextCursor(new_c)
                                event.accept()
                                return
                    elif event.key() == Qt.Key.Key_Left:
                        for tm in re.finditer(r"<{0,1}(?:mark|span|u|/mark|/span|/u)[^>]*>", line_text, re.IGNORECASE):
                            ts, te = tm.span()
                            if pos_in_block == te:
                                new_c = QTextCursor(cursor)
                                new_c.setPosition(block.position() + ts)
                                self.setTextCursor(new_c)
                                event.accept()
                                return

        # Protect hidden HTML tags against accidental character deletion on Backspace or Delete
        if not cursor.hasSelection():
            if "<" in line_text or "mark" in line_text or "span" in line_text:
                if event.key() == Qt.Key.Key_Backspace:
                    tags = list(re.finditer(r"<{0,1}(?:mark|span|u|/mark|/span|/u)[^>]*>", line_text, re.IGNORECASE))
                    for tm in tags:
                        ts, te = tm.span()
                        is_closing = tm.group().startswith(("</", "/"))
                        if not is_closing and pos_in_block == te:
                            # Caret is at start of colored text -> delete character before opening tag
                            if ts > 0:
                                cursor.beginEditBlock()
                                del_c = QTextCursor(self.document())
                                del_c.setPosition(block.position() + ts - 1)
                                del_c.setPosition(block.position() + ts, QTextCursor.MoveMode.KeepAnchor)
                                del_c.removeSelectedText()
                                cursor.endEditBlock()
                                self.viewport().update()
                                event.accept()
                                return
                        elif is_closing and pos_in_block == te:
                            # Caret is after closing tag -> delete the last character of colored content
                            if ts > 0:
                                cursor.beginEditBlock()
                                del_c = QTextCursor(self.document())
                                del_c.setPosition(block.position() + ts - 1)
                                del_c.setPosition(block.position() + ts, QTextCursor.MoveMode.KeepAnchor)
                                del_c.removeSelectedText()
                                cursor.endEditBlock()
                                self.viewport().update()
                                event.accept()
                                return
                elif event.key() == Qt.Key.Key_Delete:
                    tags = list(re.finditer(r"<{0,1}(?:mark|span|u|/mark|/span|/u)[^>]*>", line_text, re.IGNORECASE))
                    for tm in tags:
                        ts, te = tm.span()
                        is_closing = tm.group().startswith(("</", "/"))
                        if not is_closing and pos_in_block == ts:
                            # Caret is before opening tag -> delete the first character of colored content
                            if te < len(line_text):
                                cursor.beginEditBlock()
                                del_c = QTextCursor(self.document())
                                del_c.setPosition(block.position() + te)
                                del_c.setPosition(block.position() + te + 1, QTextCursor.MoveMode.KeepAnchor)
                                del_c.removeSelectedText()
                                cursor.endEditBlock()
                                self.viewport().update()
                                event.accept()
                                return
                        elif is_closing and pos_in_block == ts:
                            # Caret is at end of colored content -> delete character after closing tag
                            if te < len(line_text):
                                cursor.beginEditBlock()
                                del_c = QTextCursor(self.document())
                                del_c.setPosition(block.position() + te)
                                del_c.setPosition(block.position() + te + 1, QTextCursor.MoveMode.KeepAnchor)
                                del_c.removeSelectedText()
                                cursor.endEditBlock()
                                self.viewport().update()
                                event.accept()
                                return

        # 1. Backspace right after a checkbox or list marker removes prefix cleanly or unindents
        if event.key() == Qt.Key.Key_Backspace and not cursor.hasSelection():
            # Checkbox backspace
            cb_info = get_checkbox_info(line_text)
            if cb_info is not None:
                _, _, prefix_end, _ = cb_info
                if pos_in_block == prefix_end:
                    indent_len = len(line_text) - len(line_text.lstrip())
                    cursor.beginEditBlock()
                    if indent_len >= 2:
                        c = QTextCursor(block)
                        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                        c.deleteChar()
                        c.deleteChar()
                    else:
                        cursor.setPosition(block.position() + indent_len)
                        cursor.setPosition(
                            block.position() + prefix_end,
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        cursor.removeSelectedText()
                    cursor.endEditBlock()
                    self.viewport().update()
                    return

            # Bullet / Ordered list backspace
            list_m = LIST_RE.match(line_text)
            if list_m:
                indent, marker, space, _ = list_m.groups()
                marker_end = len(indent) + len(marker) + len(space)
                if pos_in_block == marker_end:
                    cursor.beginEditBlock()
                    if len(indent) >= 2:
                        c = QTextCursor(block)
                        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                        c.deleteChar()
                        c.deleteChar()
                    else:
                        c = QTextCursor(block)
                        c.setPosition(block.position() + len(indent))
                        c.setPosition(block.position() + marker_end, QTextCursor.MoveMode.KeepAnchor)
                        c.removeSelectedText()
                    cursor.endEditBlock()
                    self.viewport().update()
                    return

        # 2. Ctrl+Enter: Toggle or create checkbox
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            if is_checkbox_line(line_text):
                self._toggle_checkbox_at_block(block)
            else:
                cursor.beginEditBlock()
                cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                cursor.insertText("- [ ] ")
                cursor.endEditBlock()
                self.viewport().update()
            return

        # 3. Enter key: Auto-continue checklists and bulleted/numbered lists
        if self.smart_list and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
        ):
            continuation = get_auto_continue_prefix(line_text)
            if continuation is not None:
                if continuation == "":
                    # Empty list/checkbox item -> unindent by 2 spaces or terminate list
                    indent_len = len(line_text) - len(line_text.lstrip())
                    cursor.beginEditBlock()
                    if indent_len >= 2:
                        c = QTextCursor(block)
                        c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                        c.deleteChar()
                        c.deleteChar()
                    else:
                        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                        cursor.movePosition(
                            QTextCursor.MoveOperation.EndOfBlock,
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        cursor.removeSelectedText()
                    cursor.endEditBlock()
                    self.viewport().update()
                    return
                else:
                    cursor.beginEditBlock()
                    # Normalize "- []" on the current line to "- [ ]" if needed
                    cb_info = get_checkbox_info(line_text)
                    if cb_info is not None:
                        b_start, b_end, _, is_chk = cb_info
                        if (b_end - b_start) == 2:
                            fix_cursor = QTextCursor(block)
                            fix_cursor.setPosition(block.position() + b_start)
                            fix_cursor.setPosition(
                                block.position() + b_end,
                                QTextCursor.MoveMode.KeepAnchor,
                            )
                            fix_cursor.insertText("[x]" if is_chk else "[ ]")
                    # If splitting text and remainder starts with space, remove that space
                    tail = line_text[pos_in_block:]
                    if tail.startswith(" "):
                        del_c = QTextCursor(cursor)
                        del_c.deleteChar()
                    cursor.insertText("\n" + continuation)
                    cursor.endEditBlock()
                    self.ensureCursorVisible()
                    self.viewport().update()
                    return

        # 4. Standard Enter key / Shift+Enter: reliably insert newline without letting Qt swallow it on empty formatted lines
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            cursor.beginEditBlock()
            cursor.insertText("\n")
            cursor.endEditBlock()
            self.ensureCursorVisible()
            self.viewport().update()
            return

        # 5. Tab & Shift+Tab: Smart indentation for lists, checkboxes, selections, and text
        if event.key() == Qt.Key.Key_Tab:
            is_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if cursor.hasSelection():
                # Indent / unindent all blocks spanning the selection
                start_pos = cursor.selectionStart()
                end_pos = cursor.selectionEnd()
                b_curr = self.document().findBlock(start_pos)
                b_last = self.document().findBlock(end_pos)
                if b_last.position() == end_pos and b_last.blockNumber() > b_curr.blockNumber():
                    b_last = b_last.previous()

                cursor.beginEditBlock()
                while b_curr.isValid():
                    b_text = b_curr.text()
                    c = QTextCursor(b_curr)
                    c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    if is_shift:
                        rem = 2 if b_text.startswith("  ") else (1 if b_text.startswith(" ") else 0)
                        for _ in range(rem):
                            c.deleteChar()
                    else:
                        c.insertText("  ")
                    if b_curr.blockNumber() == b_last.blockNumber():
                        break
                    b_curr = b_curr.next()
                cursor.endEditBlock()
                self.viewport().update()
                return
            else:
                is_list_or_cb = (
                    LIST_RE.match(line_text) is not None
                    or CHECKBOX_PATTERN.match(line_text) is not None
                )
                if is_list_or_cb:
                    # Indent or unindent the entire list/checkbox line at start of block
                    cursor.beginEditBlock()
                    c = QTextCursor(block)
                    c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                    if is_shift:
                        rem = 2 if line_text.startswith("  ") else (1 if line_text.startswith(" ") else 0)
                        for _ in range(rem):
                            c.deleteChar()
                    else:
                        c.insertText("  ")
                    cursor.endEditBlock()
                    self.viewport().update()
                    return
                else:
                    cursor.beginEditBlock()
                    if is_shift:
                        rem = 2 if line_text.startswith("  ") else (1 if line_text.startswith(" ") else 0)
                        if rem > 0:
                            c = QTextCursor(block)
                            c.movePosition(QTextCursor.MoveOperation.StartOfBlock)
                            for _ in range(rem):
                                c.deleteChar()
                    else:
                        cursor.insertText("  ")
                    cursor.endEditBlock()
                    self.viewport().update()
                    return

        super().keyPressEvent(event)

    def _toggle_checkbox_at_block(self, block: QTextBlock) -> None:
        """Atomically toggle '[ ]' / '[]' <-> '[x]' in the given text block."""
        text = block.text()
        prefix_len = 0
        qm = QUOTE_RE.match(text)
        if qm:
            prefix_len = len(qm.group(1))
            text = text[prefix_len:]

        info = get_checkbox_info(text)
        if info is None:
            return

        bracket_start, bracket_end, prefix_end, is_checked = info
        replacement = "[ ] " if is_checked else "[x] "

        edit_cursor = QTextCursor(self.document())
        edit_cursor.beginEditBlock()
        edit_cursor.setPosition(block.position() + prefix_len + bracket_start)
        edit_cursor.setPosition(
            block.position() + prefix_len + max(bracket_end, prefix_end),
            QTextCursor.MoveMode.KeepAnchor,
        )
        edit_cursor.insertText(replacement)
        edit_cursor.endEditBlock()
        self.viewport().update()


class EditorPanel(QWidget):
    """Right pane editor containing metadata header, note title, and the editor canvas."""

    content_saved = pyqtSignal(str)  # Emits new content when debounced auto-save fires
    title_changed = pyqtSignal(str)  # Emits new title when debounced title editing fires
    create_note_with_content = pyqtSignal(str)  # Emitted when user types body on empty canvas
    create_note_with_title = pyqtSignal(str, str)  # Emitted when user types title on empty canvas (title, content)
    delete_requested = pyqtSignal()
    expand_notes_requested = pyqtSignal()
    open_file_requested = pyqtSignal()
    backup_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    zoom_in_requested = pyqtSignal()
    zoom_out_requested = pyqtSignal()
    zoom_reset_requested = pyqtSignal()
    zoom_changed = pyqtSignal(int)
    word_wrap_toggled = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)
        self._current_note: Optional[Note] = None

        # Debounce timer for smooth non-blocking auto-save of body content
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._trigger_auto_save)

        # Debounce timer for note title editing / renaming
        self._title_timer = QTimer(self)
        self._title_timer.setSingleShot(True)
        self._title_timer.setInterval(350)
        self._title_timer.timeout.connect(self._flush_title_change)

        # Debounce timer for word counting on large documents
        self._word_count_timer = QTimer(self)
        self._word_count_timer.setSingleShot(True)
        self._word_count_timer.setInterval(250)
        self._word_count_timer.timeout.connect(self._update_word_count)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 12)
        layout.setSpacing(6)

        # Header bar (Folder name, word count, delete button)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)

        # Button to expand notes list when collapsed
        self.expand_notes_btn = QPushButton(parent=self)
        self.expand_notes_btn.setObjectName("IconButton")
        self.expand_notes_btn.setIcon(create_notes_toggle_icon("#8e8e93", size=15))
        self.expand_notes_btn.setToolTip("Show Notes List")
        self.expand_notes_btn.setFixedSize(26, 26)
        self.expand_notes_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_notes_btn.setVisible(False)
        self.expand_notes_btn.clicked.connect(self.expand_notes_requested.emit)
        header.addWidget(self.expand_notes_btn)

        self.meta_label = QLabel("", parent=self)
        self.meta_label.setStyleSheet("color: #7a7a7a; font-size: 11px;")
        header.addWidget(self.meta_label)

        header.addStretch()

        self.word_count_label = QLabel("0 words", parent=self)
        self.word_count_label.setStyleSheet("color: #7a7a7a; font-size: 11px; padding-right: 6px;")
        header.addWidget(self.word_count_label)

        # Cloud Backup & Sync Button
        self.backup_btn = QPushButton(parent=self)
        self.backup_btn.setObjectName("IconButton")
        self.backup_btn.setIcon(create_backup_icon("#8e8e93", size=15))
        self.backup_btn.setToolTip("Cloud Backup & Version History (Ctrl+Shift+B)")
        self.backup_btn.setFixedSize(26, 26)
        self.backup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.backup_btn.clicked.connect(self.backup_requested.emit)
        header.addWidget(self.backup_btn)

        # Open Markdown File Button
        self.open_file_btn = QPushButton(parent=self)
        self.open_file_btn.setObjectName("IconButton")
        self.open_file_btn.setIcon(create_open_file_icon("#8e8e93", size=15))
        self.open_file_btn.setToolTip("Open Markdown File (Ctrl+O)")
        self.open_file_btn.setFixedSize(26, 26)
        self.open_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_file_btn.clicked.connect(self.open_file_requested.emit)
        header.addWidget(self.open_file_btn)

        # Export Note Button (PDF / HTML / Markdown)
        self.export_btn = QPushButton(parent=self)
        self.export_btn.setObjectName("IconButton")
        self.export_btn.setIcon(create_export_icon("#8e8e93", size=15))
        self.export_btn.setToolTip("Export Note (Ctrl+E)")
        self.export_btn.setFixedSize(26, 26)
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._show_export_menu)
        header.addWidget(self.export_btn)

        # Keyboard Shortcuts Cheatsheet Button (Ctrl+/)
        self.shortcuts_btn = QPushButton(parent=self)
        self.shortcuts_btn.setObjectName("IconButton")
        self.shortcuts_btn.setIcon(create_keyboard_icon("#8e8e93", size=15))
        self.shortcuts_btn.setToolTip("Keyboard Shortcuts (Ctrl+/)")
        self.shortcuts_btn.setFixedSize(26, 26)
        self.shortcuts_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.shortcuts_btn.clicked.connect(self._show_shortcuts_dialog)
        header.addWidget(self.shortcuts_btn)

        # Dedicated Settings Page Button (Ctrl+,)
        self.settings_btn = QPushButton(parent=self)
        self.settings_btn.setObjectName("IconButton")
        self.settings_btn.setIcon(create_settings_icon("#8e8e93", size=15))
        self.settings_btn.setToolTip("Settings (Ctrl+,)")
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        header.addWidget(self.settings_btn)

        layout.addLayout(header)

        # Frameless note title input (Notion/Craft aesthetic) — always enabled so users can title new notes on empty canvas
        self.title_edit = NoteTitleEdit(parent=self)
        self.title_edit.enter_pressed.connect(self._on_title_enter_or_down)
        self.title_edit.down_pressed.connect(self._on_title_enter_or_down)
        self.title_edit.textEdited.connect(self._on_title_edited)
        self.title_edit.editingFinished.connect(self._flush_title_change)
        layout.addWidget(self.title_edit)

        # Editor canvas
        self.editor = MarkdownEditor(parent=self)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.up_at_top_requested.connect(self._on_up_at_top)
        self.editor.settings_requested.connect(self.settings_requested.emit)
        self.editor.zoom_in_requested.connect(self.zoom_in_requested.emit)
        self.editor.zoom_out_requested.connect(self.zoom_out_requested.emit)
        self.editor.zoom_reset_requested.connect(self.zoom_reset_requested.emit)
        self.editor.word_wrap_toggled.connect(self.word_wrap_toggled.emit)

        # In-note Find & Replace Bar
        self.find_replace_bar = FindReplaceBar(parent=self)
        self.find_replace_bar.find_changed.connect(self._on_find_changed)
        self.find_replace_bar.find_next_requested.connect(self._on_find_next)
        self.find_replace_bar.find_prev_requested.connect(self._on_find_prev)
        self.find_replace_bar.replace_current_requested.connect(self._on_replace_current)
        self.find_replace_bar.replace_all_requested.connect(self._on_replace_all)
        self.find_replace_bar.closed.connect(self.close_find)
        self.find_replace_bar.replace_toggled.connect(self._on_find_replace_toggled)

        self.editor.find_requested.connect(self.open_find)
        self.editor.find_close_requested.connect(self.close_find)

        self.find_replace_bar.setVisible(False)

        layout.addWidget(self.editor)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Reposition the floating Find & Replace bar when the editor panel is resized."""
        super().resizeEvent(event)
        if hasattr(self, "find_replace_bar") and self.find_replace_bar.isVisible():
            self._update_find_bar_geometry()

    def _update_find_bar_geometry(self) -> None:
        """Position Find & Replace bar as a responsive floating overlay below the top-right header."""
        if not hasattr(self, "find_replace_bar"):
            return

        margin_right = 16
        available_w = max(240, self.width() - (margin_right * 2))

        # Responsive width: comfortably up to 400px on wide screens, adapting smoothly on narrow screens
        preferred_w = int(available_w * 0.45)
        bar_w = min(400, max(min(340, available_w), preferred_w))
        if bar_w > available_w:
            bar_w = available_w

        # Vertical position: anchored directly below the header
        top_y = 40
        if hasattr(self, "export_btn") and self.export_btn.isVisible():
            btn_bottom = self.export_btn.geometry().bottom()
            if btn_bottom > 0:
                top_y = btn_bottom + 6

        # Height based on sizeHint (accounts for whether Replace row is open)
        h = self.find_replace_bar.sizeHint().height()
        if h <= 0:
            h = 76 if getattr(self.find_replace_bar, "_replace_visible", False) else 42

        x = max(margin_right, self.width() - bar_w - margin_right)
        self.find_replace_bar.setGeometry(x, top_y, bar_w, h)

    def _on_find_replace_toggled(self, visible: bool) -> None:
        """Recompute floating overlay geometry when Replace row is expanded or collapsed."""
        self._update_find_bar_geometry()

    def open_find(self, replace_mode: bool = False) -> None:
        """Display Find & Replace bar and prefill with current selection if any."""
        cursor = self.editor.textCursor()
        had_text_change = False
        if cursor.hasSelection():
            sel_text = cursor.selectedText()
            if sel_text and "\u2029" not in sel_text and "\n" not in sel_text:
                if self.find_replace_bar.find_input.text() != sel_text:
                    had_text_change = True
                    self.find_replace_bar.find_input.setText(sel_text)

        self.find_replace_bar.set_replace_visible(replace_mode)
        self._update_find_bar_geometry()
        self.find_replace_bar.show()
        self.find_replace_bar.raise_()
        if replace_mode and self.find_replace_bar.find_input.text().strip():
            self.find_replace_bar.focus_replace()
        else:
            self.find_replace_bar.focus_find()

        if not had_text_change:
            self.find_replace_bar.retrigger_search()

    def close_find(self) -> None:
        """Hide Find & Replace bar, clear document highlights, and return focus to editor."""
        self.find_replace_bar.hide()
        self.editor.clear_search()
        self.editor.setFocus()

    def _on_find_changed(self, query: str, match_case: bool, whole_word: bool) -> None:
        curr, total = self.editor.find_matches(query, match_case, whole_word)
        self.find_replace_bar.set_match_status(curr, total)

    def _on_find_next(self) -> None:
        curr, total = self.editor.find_next()
        self.find_replace_bar.set_match_status(curr, total)

    def _on_find_prev(self) -> None:
        curr, total = self.editor.find_prev()
        self.find_replace_bar.set_match_status(curr, total)

    def _on_replace_current(self, replacement: str) -> None:
        curr, total = self.editor.replace_current(replacement)
        self.find_replace_bar.set_match_status(curr, total)

    def _on_replace_all(
        self, query: str, replacement: str, match_case: bool, whole_word: bool
    ) -> None:
        self.editor.replace_all(query, replacement, match_case, whole_word)
        self.find_replace_bar.set_match_status(0, 0)

    def _on_title_enter_or_down(self) -> None:
        """Move cursor from title edit into the start of the markdown editor body."""
        self._flush_title_change()
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.editor.setTextCursor(cursor)

    def _on_up_at_top(self) -> None:
        """Jump focus back into title edit when pressing Up arrow at position (0, 0)."""
        self.title_edit.setFocus()
        self.title_edit.setCursorPosition(len(self.title_edit.text()))

    def _on_title_edited(self, text: str) -> None:
        self._title_timer.start()

    def _flush_title_change(self) -> None:
        if self._title_timer.isActive():
            self._title_timer.stop()
        new_title = self.title_edit.text().strip()
        if not new_title:
            return
        if self._current_note is not None:
            if new_title != self._current_note.title:
                self.title_changed.emit(new_title)
        else:
            if self._save_timer.isActive():
                self._save_timer.stop()
            self.create_note_with_title.emit(new_title, self.editor.toPlainText())

    def _show_export_menu(self) -> None:
        """Display export format menu and launch native desktop file chooser."""
        if self._current_note is None and not self.editor.toPlainText().strip():
            return

        menu = QMenu(self)
        pdf_action = menu.addAction("Export as PDF (.pdf)")
        html_dark_action = menu.addAction("Export as HTML (Dark)")
        html_light_action = menu.addAction("Export as HTML (Light)")
        md_action = menu.addAction("Export as Markdown (.md)")

        action = menu.exec(self.export_btn.mapToGlobal(QPoint(0, self.export_btn.height() + 2)))
        if not action:
            return

        title = self.get_title()
        safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip() or "Untitled"
        content = self.get_content()

        doc_dir = Path.home() / "Documents"
        if not doc_dir.exists():
            doc_dir = Path.home()

        if action == pdf_action:
            default_path = str(doc_dir / f"{safe_title}.pdf")
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Note as PDF",
                default_path,
                "PDF Documents (*.pdf);;All Files (*)",
            )
            if file_path:
                target = Path(file_path)
                if not target.suffix:
                    target = target.with_suffix(".pdf")
                from utils.exporter import export_note_to_pdf
                if export_note_to_pdf(title, content, target):
                    QToolTip.showText(
                        self.export_btn.mapToGlobal(QPoint(0, 0)),
                        f"Exported {target.name} successfully!",
                        self.export_btn,
                    )
        elif action in (html_dark_action, html_light_action):
            is_dark = (action == html_dark_action)
            default_path = str(doc_dir / f"{safe_title}.html")
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Note as HTML",
                default_path,
                "HTML Documents (*.html);;All Files (*)",
            )
            if file_path:
                target = Path(file_path)
                if not target.suffix:
                    target = target.with_suffix(".html")
                from utils.exporter import export_note_to_html
                if export_note_to_html(title, content, target, dark_theme=is_dark):
                    QToolTip.showText(
                        self.export_btn.mapToGlobal(QPoint(0, 0)),
                        f"Exported {target.name} successfully!",
                        self.export_btn,
                    )
        elif action == md_action:
            default_path = str(doc_dir / f"{safe_title}.md")
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Export Note as Markdown",
                default_path,
                "Markdown Documents (*.md);;All Files (*)",
            )
            if file_path:
                target = Path(file_path)
                if not target.suffix:
                    target = target.with_suffix(".md")
                try:
                    target.write_text(content, encoding="utf-8")
                    QToolTip.showText(
                        self.export_btn.mapToGlobal(QPoint(0, 0)),
                        f"Exported {target.name} successfully!",
                        self.export_btn,
                    )
                except Exception:
                    pass

    def export_current_note(self) -> None:
        """Trigger export menu from shortcut (Ctrl+E)."""
        self._show_export_menu()

    def _show_shortcuts_dialog(self) -> None:
        """Open the modern keyboard shortcuts reference cheatsheet modal."""
        from ui.shortcuts_dialog import ModernShortcutsDialog
        ModernShortcutsDialog.show_shortcuts(self.window())

    def load_note(self, note: Optional[Note]) -> None:
        """Load note markdown into the editor as pure plain text with live highlighting."""
        self._current_note = note
        self._save_timer.stop()
        self.editor.slash_palette.hide()
        if hasattr(self.editor, "format_toolbar"):
            self.editor.format_toolbar.hide()
        if self._title_timer.isActive():
            self._title_timer.stop()

        if note is None:
            self.export_btn.setEnabled(False)
            self.title_edit.blockSignals(True)
            self.title_edit.setText("")
            self.title_edit.setEnabled(True)
            self.title_edit.blockSignals(False)

            self.editor.blockSignals(True)
            self.editor.setPlainText("")
            self.meta_label.setText("No note selected")
            self.word_count_label.setText("0 words")
            self.editor._transient_scrollbar.hide_immediately()
            self.editor.blockSignals(False)
            return

        self.export_btn.setEnabled(True)
        self.title_edit.setEnabled(True)
        self.title_edit.blockSignals(True)
        self.title_edit.setText(note.title)
        self.title_edit.blockSignals(False)

        # Clean any accidental escaped headings (\# ) and normalize "- []" to "- [ ]"
        cleaned_content = note.content
        if "\\#" in cleaned_content:
            cleaned_content = re.sub(r"^\\(#+\s)", r"\1", cleaned_content, flags=re.MULTILINE)
        if "[]" in cleaned_content:
            cleaned_content = re.sub(
                r"^(\s*[-*+]\s*)\[\](?=\s|$)", r"\1[ ]", cleaned_content, flags=re.MULTILINE
            )

        self.editor._table_scroll_x.clear()
        self.editor._code_scroll_x.clear()
        self.editor._copied_code_block = None
        self.editor._scrollbar_drag = None
        self.editor._transient_scrollbar.hide_immediately()
        self._word_count_timer.stop()

        self.editor.blockSignals(True)
        self.editor.setPlainText(cleaned_content)
        self.editor.viewport().update()
        self.editor.blockSignals(False)

        self.update_meta(note)
        self._update_word_count()

        if hasattr(self, "find_replace_bar") and self.find_replace_bar.isVisible() and self.find_replace_bar.find_input.text():
            self.find_replace_bar.retrigger_search()
        else:
            self.editor.clear_search()

    def update_meta(self, note: Note) -> None:
        """Update only the metadata header without reloading the editor document."""
        self._current_note = note
        self.export_btn.setEnabled(True)
        self.title_edit.setEnabled(True)
        folder_name = note.path.parent.name
        self.meta_label.setText(f"{folder_name}  •  Edited {note.formatted_time}")
        if not self.title_edit.hasFocus() and self.title_edit.text() != note.title:
            self.title_edit.blockSignals(True)
            self.title_edit.setText(note.title)
            self.title_edit.blockSignals(False)

    def set_backup_changes_count(self, count: int) -> None:
        """Update the top-right cloud backup icon with a pending changes indicator."""
        has_changes = count > 0
        color = "#e5a93c" if has_changes else "#8e8e93"
        self.backup_btn.setIcon(create_backup_icon(color, size=15, has_dot=has_changes))
        tip = (
            f"Cloud Backup & Version History ({count} unsynced changes)"
            if has_changes
            else "Cloud Backup & Version History (Ctrl+Shift+B)"
        )
        self.backup_btn.setToolTip(tip)

    def get_title(self) -> str:
        """Return the current title edit text."""
        return self.title_edit.text().strip() or "Untitled"

    def get_content(self) -> str:
        """Return the pure plain-text Markdown content."""
        return self.editor.toPlainText()

    def _on_text_changed(self) -> None:
        if self.editor.document().blockCount() > 400:
            self._word_count_timer.start()
        else:
            self._word_count_timer.stop()
            self._update_word_count()
        self._save_timer.start()
        if hasattr(self, "find_replace_bar") and self.find_replace_bar.isVisible() and self.find_replace_bar.find_input.text():
            self.find_replace_bar.retrigger_search()

    def _update_word_count(self) -> None:
        words = count_words_fast(self.editor.toPlainText())
        self.word_count_label.setText(f"{words} words")

    def flush_pending_save(self) -> None:
        """Immediately flush any pending debounced save before application exit or switch."""
        if self._title_timer.isActive():
            self._flush_title_change()
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._trigger_auto_save()

    def _trigger_auto_save(self) -> None:
        """Emit save signal with latest Markdown text."""
        content = self.editor.toPlainText()
        if self._current_note is None:
            pending_title = self.title_edit.text().strip()
            if pending_title:
                if self._title_timer.isActive():
                    self._title_timer.stop()
                self.create_note_with_title.emit(pending_title, content)
            elif content.strip():
                self.create_note_with_content.emit(content)
        else:
            self.content_saved.emit(content)

    def zoom_in(self) -> None:
        """Request UI zoom in."""
        self.zoom_in_requested.emit()

    def zoom_out(self) -> None:
        """Request UI zoom out."""
        self.zoom_out_requested.emit()

    def zoom_reset(self) -> None:
        """Request UI zoom reset."""
        self.zoom_reset_requested.emit()

    def toggle_word_wrap(self) -> bool:
        """Toggle soft word wrap on the underlying markdown editor."""
        return self.editor.toggle_word_wrap()

    def set_ui_scale(self, scale: float) -> None:
        """Propagate UI scale to markdown editor."""
        self.editor.set_ui_scale(scale)

    def apply_config(self, config: Any, ui_scale: float = 1.0) -> None:
        """Apply live configuration settings to the editor canvas with optional UI scaling."""
        if hasattr(config, "general") and hasattr(config.general, "ui_scale"):
            ui_scale = getattr(config.general, "ui_scale", 1.0)
        self.editor.set_ui_scale(ui_scale)

        if hasattr(config, "editor"):
            self._save_timer.setInterval(config.editor.auto_save_delay_ms)
            scaled_font_size = max(8, int(round(config.editor.font_size * ui_scale)))
            self.editor._font_size_pt = scaled_font_size
            if config.editor.font_family and config.editor.font_family != "System":
                self.editor._font_family = config.editor.font_family
            font = self.editor.font()
            font.setPointSize(scaled_font_size)
            if config.editor.font_family and config.editor.font_family != "System":
                font.setFamily(config.editor.font_family)
            self.editor.setFont(font)
            self.editor.document().setDefaultFont(font)
            mode = QTextEdit.LineWrapMode.WidgetWidth if config.editor.word_wrap else QTextEdit.LineWrapMode.NoWrap
            self.editor.setLineWrapMode(mode)
            if config.editor.word_wrap and hasattr(self.editor, "_transient_h_scrollbar"):
                self.editor._transient_h_scrollbar.hide_immediately()
            metrics = self.editor.fontMetrics()
            self.editor._tab_size = config.editor.tab_size
            self.editor.setTabStopDistance(float(metrics.horizontalAdvance(' ') * config.editor.tab_size))

            # Scale note title font size proportionally with ui_scale (default 26px)
            scaled_title_pt = max(16, int(round(26 * ui_scale)))
            h_pad = getattr(config.editor, "horizontal_padding", 36)
            scaled_h_pad = max(8, int(round(h_pad * ui_scale)))
            self.title_edit.setStyleSheet(f"""
                QLineEdit#NoteTitleEdit {{
                    background-color: transparent;
                    border: none;
                    color: #ffffff;
                    font-size: {scaled_title_pt}px;
                    font-weight: 700;
                    padding: 10px {scaled_h_pad}px 4px {scaled_h_pad}px;
                    selection-background-color: #0a84ff;
                }}
                QLineEdit#NoteTitleEdit:focus {{
                    border: none;
                    background-color: transparent;
                }}
                QLineEdit#NoteTitleEdit:disabled {{
                    color: #555555;
                }}
            """)
            self.editor._horizontal_padding = scaled_h_pad
            self.editor._refresh_editor_style()

        # Scale status/metadata labels proportionally
        scaled_meta_pt = max(8, int(round(11 * ui_scale)))
        self.meta_label.setStyleSheet(f"color: #7a7a7a; font-size: {scaled_meta_pt}px;")
        self.word_count_label.setStyleSheet(f"color: #7a7a7a; font-size: {scaled_meta_pt}px; padding-right: 6px;")

        self.editor.highlighter.ui_scale = ui_scale

        if hasattr(config, "markdown"):
            self.editor.render_latex = getattr(config.markdown, "render_latex", True)
            self.editor.render_mermaid = getattr(config.markdown, "render_mermaid", True)
            self.editor.smart_list = getattr(config.markdown, "smart_list", True)
            self.editor.code_line_numbers = getattr(config.markdown, "code_line_numbers", False)

        self.editor.highlighter.rehighlight()
        self.editor.viewport().update()
        if hasattr(config, "editor"):
            self.zoom_changed.emit(scaled_font_size)

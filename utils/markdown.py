"""Utility functions for parsing and manipulating Markdown text."""

import re
from typing import Optional, Tuple

from PyQt6.QtGui import QFont, QFontMetricsF

CHECKBOX_PATTERN = re.compile(r"^(\s*)([-*+]\s*\[([ xX]?)\]\s?)(.*)$")
LIST_PATTERN = re.compile(r"^(\s*)([-*+]|\d+\.|\d+\))(\s+)(.*)$")
QUOTE_PATTERN = re.compile(r"^(\s*(?:>[ \t]*)+)")
LINK_PATTERN = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<url>[^\s)]+)\)|<(?P<autourl>https?://[^\s>]+)>|(?P<rawurl>https?://[^\s<>\)\]`]+)"
)


def calculate_block_hanging_indent(
    text: str,
    font: QFont,
    ui_scale: float = 1.0,
) -> Tuple[float, float]:
    """Calculate (left_margin, text_indent) for a line of text in Markdown.

    Handles:
    - Blockquotes ("> ", ">> ")
    - Checkboxes ("- [ ]", "* [x]", "  - [ ]", etc.)
    - Bullet lists ("- ", "* ", "+ ", "  - ", etc.)
    - Numbered lists ("1. ", "10. ", "  1) ", etc.)
    - Blockquoted lists and checkboxes (e.g. "> - [ ] ")

    Returns:
        (left_margin, text_indent) as floats.
        For normal unindented text, returns (0.0, 0.0).
        For list/checkbox items, text_indent is negative such that:
          first line starts at left_margin + text_indent (the indent level)
          continuation lines wrap to left_margin (aligned with text after marker)
    """
    quote_margin = 0.0
    inner_text = text
    qm = QUOTE_PATTERN.match(text)
    if qm:
        prefix_q = qm.group(1)
        level = prefix_q.count(">")
        if level > 0:
            quote_margin = level * 18.0 + 8.0
        inner_text = text[len(prefix_q):]

    fm = QFontMetricsF(font)
    cb_match = CHECKBOX_PATTERN.match(inner_text)
    if cb_match:
        indent, prefix, _, _ = cb_match.groups()
        indent_w = fm.horizontalAdvance(indent)
        marker = prefix.strip()[0] if prefix.strip() else "-"
        canonical_prefix = f"{marker} [ ] "
        marker_w = fm.horizontalAdvance(canonical_prefix)
        return round(quote_margin + indent_w + marker_w, 2), round(-marker_w, 2)

    list_match = LIST_PATTERN.match(inner_text)
    if list_match:
        indent, marker, space, _ = list_match.groups()
        indent_w = fm.horizontalAdvance(indent)
        if marker in ("-", "*", "+"):
            marker_w = fm.horizontalAdvance(marker + space) + len(marker + space) * round(10.0 * ui_scale, 1)
        else:
            bold_font = QFont(font)
            bold_font.setWeight(QFont.Weight.Bold)
            fm_bold = QFontMetricsF(bold_font)
            marker_w = fm_bold.horizontalAdvance(marker) + fm.horizontalAdvance(space) + len(space) * round(14.0 * ui_scale, 1)
        return round(quote_margin + indent_w + marker_w, 2), round(-marker_w, 2)

    if quote_margin > 0.0:
        return round(quote_margin, 2), 0.0

    return 0.0, 0.0


def find_link_at_offset(text: str, offset: int) -> Optional[Tuple[int, int, str]]:
    """Return (start, end, url) if offset falls within a Markdown link or URL in text."""
    for m in LINK_PATTERN.finditer(text):
        start, end = m.span()
        if m.group("rawurl"):
            raw = m.group("rawurl")
            trimmed = raw.rstrip(".,;:!?*~'\"")
            end = start + len(trimmed)
            url = trimmed
        else:
            url = m.group("url") or m.group("autourl")
        if start <= offset <= end:
            return start, end, url
    return None


def is_checkbox_line(line: str) -> bool:
    """Return True if the line contains a markdown checklist item."""
    return CHECKBOX_PATTERN.match(line) is not None


def get_checkbox_info(line: str) -> Optional[Tuple[int, int, int, bool]]:
    """Return (bracket_start, bracket_end, prefix_end, is_checked) if present.

    Example:
        For "- [ ] task", returns (2, 5, 6, False)
        For "- [] task", returns (2, 4, 5, False)
    """
    match = CHECKBOX_PATTERN.match(line)
    if not match:
        return None

    indent, prefix, status_char, _ = match.groups()
    is_checked = status_char.lower() == "x"
    bracket_start = line.find("[", len(indent))
    bracket_end = line.find("]", bracket_start) + 1
    prefix_end = len(indent) + len(prefix)
    return bracket_start, bracket_end, prefix_end, is_checked


def toggle_checkbox_line(line: str) -> str:
    """Toggle the checkbox state between '- [ ]' and '- [x]' in a line."""
    match = CHECKBOX_PATTERN.match(line)
    if not match:
        return line

    indent, prefix, status_char, rest = match.groups()
    marker = prefix.strip()[0]
    new_char = " " if status_char.lower() == "x" else "x"
    return f"{indent}{marker} [{new_char}] {rest}"


def get_auto_continue_prefix(line: str) -> Optional[str]:
    """Determine the prefix to continue on the next line when Enter is pressed.

    Returns:
        - None if line is not a list/checkbox
        - Empty string "" if line was an empty list marker (signaling to delete it)
        - Continued prefix (e.g. "- [ ] ", "- ", "2. ") if line had content
    """
    # Checkbox item
    cb_match = CHECKBOX_PATTERN.match(line)
    if cb_match:
        indent, prefix, _, rest = cb_match.groups()
        if not rest.strip():
            # Empty checkbox item -> terminate list
            return ""
        # Return new unchecked box for next line with same indent
        marker = prefix.strip()[0]  # '-', '*', or '+'
        return f"{indent}{marker} [ ] "

    # Regular bullet or numbered list
    list_match = LIST_PATTERN.match(line)
    if list_match:
        indent, marker, space, rest = list_match.groups()
        if not rest.strip():
            # Empty list item -> terminate list
            return ""
        if marker[:-1].isdigit() and (marker.endswith(".") or marker.endswith(")")):
            num = int(marker[:-1])
            delim = marker[-1]
            return f"{indent}{num + 1}{delim} "
        return f"{indent}{marker}{space}"

    return None


BLOCK_PREFIX_PATTERN = re.compile(
    r"^(\s*[-*+]?\s*\[[ xX]?\]\s*|\s*[-*+]\s+|\s*\d+[\.\)]\s+|\s*#{1,6}\s*|\s*>\s*)"
)


def transform_line_block_prefix(line_text: str, new_prefix: str) -> str:
    """Transform an existing line's prefix (bullet, checkbox, number, heading, quote) to a new prefix.

    Preserves leading indentation and core content while stripping any previous marker.
    Preserves [x] checked state when transforming an already-checked checkbox to a checkbox.
    """
    indent = line_text[: len(line_text) - len(line_text.lstrip())]
    line_no_indent = line_text[len(indent) :]

    was_checked = bool(re.match(r"^[-*+]?\s*\[[xX]\]", line_no_indent.strip()))

    m = BLOCK_PREFIX_PATTERN.match(line_no_indent)
    if m:
        core_text = line_no_indent[m.end() :]
    else:
        trimmed = line_no_indent.strip()
        if trimmed in ("-", "*", "+", "- []", "- [ ]", "- [x]", "- [X]", ">", "#", "##", "###"):
            core_text = ""
        else:
            core_text = line_no_indent

    target_prefix = new_prefix
    if was_checked and target_prefix.startswith("- [ ]"):
        target_prefix = target_prefix.replace("[ ]", "[x]")

    return f"{indent}{target_prefix}{core_text}"


STRUCTURAL_PREFIX_PATTERN = re.compile(
    r"^(\s*(?:>+\s*)*(?:[-*+]\s*\[[ xX]?\]\s*|[-*+]\s+|\d+[\.\)]\s+|#{1,6}\s+))(.*)$"
)

SPAN_COLOR_TAG_PATTERN = re.compile(
    r"^<{0,1}span\s+style=[\"']color:\s*([#a-zA-Z0-9]+);?[\"']>(.*?)</{0,1}span>$",
    re.DOTALL | re.IGNORECASE,
)

MARK_COLOR_TAG_PATTERN = re.compile(
    r"^<{0,1}mark(?:\s+style=[\"']background(?:-color)?:\s*([#a-zA-Z0-9]+);?[\"'])?>(.*?)</{0,1}mark>$",
    re.DOTALL | re.IGNORECASE,
)


def expand_selection_to_color_tags(
    doc_text: str,
    start: int,
    end: int,
    tag_kind: str,
) -> tuple[int, int]:
    """Expand selection bounds to enclose any immediately adjacent or enclosing color tags."""
    if tag_kind == "mark":
        open_pat = re.compile(r"<{0,1}mark(?:\s+style=[^>]+)?>", re.IGNORECASE)
        close_pat = re.compile(r"</{0,1}mark>", re.IGNORECASE)
    else:
        open_pat = re.compile(r"<{0,1}span(?:\s+style=[\"']color:[^>]+[\"'])?>", re.IGNORECASE)
        close_pat = re.compile(r"</{0,1}span>", re.IGNORECASE)

    new_start = start
    new_end = end

    for m in open_pat.finditer(doc_text[:start]):
        if m.end() == start or m.start() <= start < m.end():
            new_start = m.start()
            break

    for m in close_pat.finditer(doc_text[end:]):
        if m.start() == 0 or m.start() <= 0 < m.end():
            new_end = end + m.end()
            break

    return new_start, new_end


def _format_single_line_text_color(line: str, color: str) -> str:
    """Apply, change, or remove text color on a single line, preserving list/checkbox prefixes."""
    if not line.strip():
        return line

    line_trailing_ws = ""
    while line and line[-1] in (" ", "\t"):
        line_trailing_ws = line[-1] + line_trailing_ws
        line = line[:-1]

    struct_match = STRUCTURAL_PREFIX_PATTERN.match(line)
    lead_prefix = struct_match.group(1) if struct_match else ""
    core_text = struct_match.group(2) if struct_match else line

    # Always strip all existing text color spans within the core selection
    cleaned_core = re.sub(
        r"<{0,1}/?span(?:\s+style=[\"']color:[^>]+[\"'])?>",
        "",
        core_text,
        flags=re.IGNORECASE,
    )

    if not color:
        # Default / Reset: return clean text without color tags
        formatted_core = cleaned_core
    else:
        # Check if the selection was already uniformly colored with the exact same color -> toggle off
        m = SPAN_COLOR_TAG_PATTERN.match(core_text.strip())
        if m and m.group(1).lower() == color.lower():
            formatted_core = cleaned_core
        else:
            formatted_core = f'<span style="color: {color};">{cleaned_core}</span>'

    return f"{lead_prefix}{formatted_core}{line_trailing_ws}"


def apply_text_color_to_markdown(text: str, color: str) -> str:
    """Apply, change, or remove inline text color across single or multiple selected lines."""
    parts = re.split(r"(\r?\n|\u2029)", text)
    formatted_parts = []
    for p in parts:
        if p in ("\n", "\r\n", "\u2029"):
            formatted_parts.append("\n")
        else:
            formatted_parts.append(_format_single_line_text_color(p, color))
    return "".join(formatted_parts)


def _format_single_line_highlight_color(line: str, color: str) -> str:
    """Apply, change, or remove background highlight on a single line, preserving prefixes."""
    if not line.strip():
        return line

    line_trailing_ws = ""
    while line and line[-1] in (" ", "\t"):
        line_trailing_ws = line[-1] + line_trailing_ws
        line = line[:-1]

    struct_match = STRUCTURAL_PREFIX_PATTERN.match(line)
    lead_prefix = struct_match.group(1) if struct_match else ""
    core_text = struct_match.group(2) if struct_match else line

    # Always strip all existing mark tags within the core selection
    cleaned_core = re.sub(
        r"<{0,1}/?mark(?:\s+style=[^>]+)?>",
        "",
        core_text,
        flags=re.IGNORECASE,
    )

    if not color:
        # None / Reset: return clean text without highlight tags
        formatted_core = cleaned_core
    else:
        # Check if the selection was already uniformly highlighted with the exact same color -> toggle off
        m = MARK_COLOR_TAG_PATTERN.match(core_text.strip())
        if m and (m.group(1) or "#ffd60a").lower() == color.lower():
            formatted_core = cleaned_core
        else:
            formatted_core = f'<mark style="background-color: {color};">{cleaned_core}</mark>'

    return f"{lead_prefix}{formatted_core}{line_trailing_ws}"


def apply_highlight_color_to_markdown(text: str, color: str) -> str:
    """Apply, change, or remove inline background highlight across single or multiple selected lines."""
    parts = re.split(r"(\r?\n|\u2029)", text)
    formatted_parts = []
    for p in parts:
        if p in ("\n", "\r\n", "\u2029"):
            formatted_parts.append("\n")
        else:
            formatted_parts.append(_format_single_line_highlight_color(p, color))
    return "".join(formatted_parts)

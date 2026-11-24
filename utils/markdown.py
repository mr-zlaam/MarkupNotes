"""Utility functions for parsing and manipulating Markdown text."""

import re
from typing import Dict, Optional, Tuple
from urllib.parse import unquote

from PyQt6.QtGui import QFont, QFontMetricsF, QTextDocument

CHECKBOX_PATTERN = re.compile(r"^(\s*)([-*+]\s*\[([ xX]?)\]\s?)(.*)$")
LIST_PATTERN = re.compile(r"^(\s*)([-*+]|\d+\.|\d+\))(\s+)(.*)$")
QUOTE_PATTERN = re.compile(r"^(\s*(?:>[ \t]*)+)")
LINK_PATTERN = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<url>[^\s)]+)\)|<(?P<autourl>https?://[^\s>]+)>|(?P<rawurl>https?://[^\s<>\)\]`]+)"
)


_HANGING_PREFIX_CHARS = frozenset(" \t>-*+0123456789")


def calculate_block_hanging_indent(
    text: str,
    font: QFont,
    ui_scale: float = 1.0,
    fm: Optional[QFontMetricsF] = None,
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
    if not text or text[0] not in _HANGING_PREFIX_CHARS:
        return 0.0, 0.0

    quote_margin = 0.0
    inner_text = text
    qm = QUOTE_PATTERN.match(text)
    if qm:
        prefix_q = qm.group(1)
        level = prefix_q.count(">")
        if level > 0:
            quote_margin = level * 18.0 + 8.0
        inner_text = text[len(prefix_q):]

    if not inner_text or inner_text[0] not in _HANGING_PREFIX_CHARS:
        return (round(quote_margin, 2), 0.0) if quote_margin > 0.0 else (0.0, 0.0)

    metrics = fm if fm is not None else QFontMetricsF(font)
    cb_match = CHECKBOX_PATTERN.match(inner_text)
    if cb_match:
        indent, prefix, _, _ = cb_match.groups()
        indent_w = metrics.horizontalAdvance(indent)
        marker = prefix.strip()[0] if prefix.strip() else "-"
        canonical_prefix = f"{marker} [ ] "
        marker_w = metrics.horizontalAdvance(canonical_prefix)
        return round(quote_margin + indent_w + marker_w, 2), round(-marker_w, 2)

    list_match = LIST_PATTERN.match(inner_text)
    if list_match:
        indent, marker, space, _ = list_match.groups()
        indent_w = metrics.horizontalAdvance(indent)
        if marker in ("-", "*", "+"):
            marker_w = metrics.horizontalAdvance(marker + space) + len(marker + space) * round(10.0 * ui_scale, 1)
        else:
            bold_font = QFont(font)
            bold_font.setWeight(QFont.Weight.Bold)
            fm_bold = QFontMetricsF(bold_font)
            marker_w = fm_bold.horizontalAdvance(marker) + metrics.horizontalAdvance(space) + len(space) * round(14.0 * ui_scale, 1)
        return round(quote_margin + indent_w + marker_w, 2), round(-marker_w, 2)

    if quote_margin > 0.0:
        return round(quote_margin, 2), 0.0

    return 0.0, 0.0


def find_link_details_at_offset(text: str, offset: int) -> Optional[Tuple[int, int, str, str]]:
    """Return (start, end, label, url) if offset falls within a Markdown link or URL in text."""
    for m in LINK_PATTERN.finditer(text):
        start, end = m.span()
        if m.group("rawurl"):
            raw = m.group("rawurl")
            trimmed = raw.rstrip(".,;:!?*~'\"")
            end = start + len(trimmed)
            url = trimmed
            label = trimmed
        else:
            url = m.group("url") or m.group("autourl") or ""
            label = m.group("label") or url
        if start <= offset <= end:
            return start, end, label, url
    return None


def find_link_at_offset(text: str, offset: int) -> Optional[Tuple[int, int, str]]:
    """Return (start, end, url) if offset falls within a Markdown link or URL in text."""
    details = find_link_details_at_offset(text, offset)
    if details is None:
        return None
    start, end, _, url = details
    return start, end, url


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
    r"^(\s*(?:>+[ \t]*)+(?:[-*+]\s*\[[ xX]?\][ \t]*|[-*+][ \t]+|\d+[\.\)][ \t]+|#{1,6}[ \t]+)?|\s*(?:[-*+]\s*\[[ xX]?\][ \t]*|[-*+][ \t]+|\d+[\.\)][ \t]+|#{1,6}[ \t]+))(.*)$"
)


def trim_selection_past_structural_prefixes(
    doc_text: str,
    start: int,
    end: int,
) -> Optional[Tuple[int, int]]:
    """Trim selection bounds so structural markdown prefixes are never partially or fully wrapped.

    Returns adjusted (start, end) or None if the selection covers only structural prefix characters.
    """
    if start >= end or start < 0 or end > len(doc_text):
        return None

    new_start = start
    new_end = end

    # 1. Inspect the starting line and push start past its structural prefix if needed
    start_line_pos = doc_text.rfind("\n", 0, new_start) + 1
    start_line_end = doc_text.find("\n", start_line_pos)
    if start_line_end == -1:
        start_line_end = len(doc_text)

    start_line = doc_text[start_line_pos:start_line_end]
    m_start = STRUCTURAL_PREFIX_PATTERN.match(start_line)
    if m_start:
        prefix_end = start_line_pos + len(m_start.group(1))
        if new_start < prefix_end:
            if new_end <= prefix_end:
                return None
            new_start = prefix_end

    # 2. If selection spans multiple lines and ends inside the last line's prefix, trim end back
    if new_end > start_line_end:
        end_line_pos = doc_text.rfind("\n", 0, new_end) + 1
        if end_line_pos > start_line_pos and new_end > end_line_pos:
            end_line_end = doc_text.find("\n", end_line_pos)
            if end_line_end == -1:
                end_line_end = len(doc_text)
            end_line = doc_text[end_line_pos:end_line_end]
            m_end = STRUCTURAL_PREFIX_PATTERN.match(end_line)
            if m_end:
                end_prefix_end = end_line_pos + len(m_end.group(1))
                if new_end <= end_prefix_end:
                    new_end = end_line_pos - 1

    if new_start >= new_end:
        return None
    return new_start, new_end

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

    if not color or not cleaned_core.strip():
        # Default / Reset or prefix-only line: return clean text without color tags
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

    if not color or not cleaned_core.strip():
        # None / Reset or prefix-only line: return clean text without highlight tags
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


_HEADING_ANCHOR_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$")
_HTML_ANCHOR_ID_RE = re.compile(
    r"""<(?:a|span|div|h[1-6])\b[^>]*\b(?:id|name)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_FENCE_TOGGLE_RE = re.compile(r"^\s*(?:>+\s*)*```")


def is_internal_toc_link(url: str) -> bool:
    """Return True if url is an in-document '#anchor' or EPUB-style relative '.html'/'.xhtml' TOC link."""
    clean = url.strip()
    if not clean:
        return False
    if clean.startswith("#"):
        return True
    lower = clean.lower()
    if lower.startswith(("http://", "https://", "mailto:", "file://", "ftp://")):
        return False
    path_part = lower.split("#", 1)[0].split("?", 1)[0]
    return path_part.endswith((".html", ".xhtml", ".htm"))


def slugify_heading(heading_text: str) -> str:
    """Convert Markdown heading text into a GitHub-compatible lowercase anchor slug."""
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading_text)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"[*_~`]+", "", cleaned)
    cleaned = (
        cleaned.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    cleaned = cleaned.strip().lower()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned.strip("-")


def find_anchor_block_number(
    doc: QTextDocument,
    anchor: str,
    *,
    label: str = "",
    exclude_block: int = -1,
) -> Optional[int]:
    """Find the block number matching a TOC anchor ('#slug' or 'page-89.html') or link label text.

    Supports GitHub-style heading slugs (including duplicate '-1'/'-2' suffixes),
    explicit HTML id/name anchors, and EPUB-style label-to-heading matching while skipping code blocks.
    """
    raw_anchor = unquote(anchor.strip())
    fragment = ""
    if "#" in raw_anchor:
        fragment = raw_anchor.split("#", 1)[1].strip().lower()
    elif raw_anchor.startswith("#"):
        fragment = raw_anchor[1:].strip().lower()

    file_target = raw_anchor.split("#", 1)[0].split("?", 1)[0].strip().lower()
    file_stem = file_target.rsplit(".", 1)[0] if "." in file_target else file_target

    target = fragment or file_target
    target_collapsed = re.sub(r"-+", "-", target) if target else ""
    label_slug = slugify_heading(label) if label else ""
    label_lower = label.strip().lower() if label else ""

    if not target and not label_slug:
        return None

    slug_counts: Dict[str, int] = {}
    in_code_block = False
    label_heading_block: Optional[int] = None
    label_text_block: Optional[int] = None
    fallback_block: Optional[int] = None

    block = doc.firstBlock()
    while block.isValid():
        bn = block.blockNumber()
        text = block.text()
        if _FENCE_TOGGLE_RE.match(text):
            in_code_block = not in_code_block
            block = block.next()
            continue

        if not in_code_block and bn != exclude_block:
            # 1. Explicit HTML id/name anchor match
            if target and "<" in text and ("id=" in text.lower() or "name=" in text.lower()):
                for m_id in _HTML_ANCHOR_ID_RE.finditer(text):
                    val = m_id.group(1).strip().lower()
                    if val == target or (file_stem and val == file_stem):
                        return bn

            # 2. Markdown heading match
            hm = _HEADING_ANCHOR_RE.match(text)
            if hm:
                heading_body = hm.group(1)
                base_slug = slugify_heading(heading_body)
                if base_slug:
                    seen_count = slug_counts.get(base_slug, 0)
                    slug_counts[base_slug] = seen_count + 1
                    candidate_slug = base_slug if seen_count == 0 else f"{base_slug}-{seen_count}"
                    if fragment and candidate_slug == fragment:
                        return bn
                    if label_slug and label_heading_block is None and base_slug == label_slug:
                        label_heading_block = bn
                    if fallback_block is None and target:
                        collapsed = re.sub(r"-+", "-", candidate_slug)
                        if collapsed == target_collapsed or heading_body.strip().lower() == target:
                            fallback_block = bn
            elif label_slug and label_text_block is None and "[" not in text:
                # 3. Fallback for EPUB-converted plain chapter title lines without '#' prefix
                stripped = text.strip()
                if stripped and (
                    stripped.lower() == label_lower or slugify_heading(stripped) == label_slug
                ):
                    label_text_block = bn

        block = block.next()

    if label_heading_block is not None:
        return label_heading_block
    if fallback_block is not None:
        return fallback_block
    return label_text_block

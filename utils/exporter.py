"""Export utility for converting Markup Notes markdown into styled PDF and HTML documents."""

import base64
import logging
from pathlib import Path
import re
from typing import Optional

from PyQt6.QtCore import QMarginsF
from PyQt6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

logger = logging.getLogger(__name__)

PDF_STYLE = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Cantarell", "Segoe UI", "Ubuntu", sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1e;
    margin: 0;
    padding: 0;
}
h1 {
    font-size: 22pt;
    font-weight: 700;
    color: #111114;
    margin-top: 0;
    margin-bottom: 12px;
    padding-bottom: 4px;
    border-bottom: 1px solid #e0e0e4;
}
h2 {
    font-size: 16pt;
    font-weight: 600;
    color: #222226;
    margin-top: 16px;
    margin-bottom: 8px;
}
h3 {
    font-size: 13pt;
    font-weight: 600;
    color: #333338;
    margin-top: 12px;
    margin-bottom: 6px;
}
p {
    margin-top: 0;
    margin-bottom: 10px;
}
pre, code {
    font-family: "JetBrains Mono", "Fira Code", "Source Code Pro", "Monospace", monospace;
    font-size: 9.5pt;
    background-color: #f4f4f7;
    border-radius: 4px;
}
pre {
    padding: 10px 14px;
    margin: 12px 0;
    border: 1px solid #e2e2e8;
}
code {
    padding: 2px 4px;
}
blockquote {
    border-left: 3px solid #0a84ff;
    padding-left: 12px;
    margin-left: 0;
    color: #55555e;
    font-style: italic;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
}
th, td {
    border: 1px solid #d4d4dc;
    padding: 6px 10px;
    text-align: left;
}
th {
    background-color: #f0f0f4;
    font-weight: 600;
}
hr {
    border: none;
    border-top: 1px solid #dcdce2;
    margin: 16px 0;
}
ul, ol {
    margin-top: 0;
    margin-bottom: 10px;
    padding-left: 24px;
}
li {
    margin-bottom: 4px;
}
li.task-item {
    list-style-type: none;
    margin-left: -14px;
    margin-bottom: 4px;
}
li.task-item.checked {
    color: #8e8e93;
}
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
        :root {{
            --bg-color: {bg_color};
            --text-color: {text_color};
            --heading-color: {heading_color};
            --code-bg: {code_bg};
            --border-color: {border_color};
            --accent-color: #0a84ff;
        }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Cantarell", "Segoe UI", "Ubuntu", sans-serif;
            line-height: 1.65;
            margin: 0;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 820px;
            margin: 0 auto;
            background-color: var(--bg-color);
        }}
        h1, h2, h3, h4, h5, h6 {{
            color: var(--heading-color);
            margin-top: 1.4em;
            margin-bottom: 0.6em;
            font-weight: 600;
        }}
        h1 {{
            font-size: 2.2em;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.3em;
            margin-top: 0;
        }}
        h2 {{ font-size: 1.6em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.2em; }}
        h3 {{ font-size: 1.3em; }}
        p {{ margin: 0.8em 0; }}
        a {{ color: var(--accent-color); text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        pre, code {{
            font-family: "JetBrains Mono", "Fira Code", "Source Code Pro", "Monospace", monospace;
            font-size: 0.9em;
            background-color: var(--code-bg);
            border-radius: 5px;
        }}
        pre {{
            padding: 14px 18px;
            overflow-x: auto;
            border: 1px solid var(--border-color);
        }}
        code {{
            padding: 2px 6px;
        }}
        blockquote {{
            border-left: 4px solid var(--accent-color);
            padding-left: 14px;
            margin: 1em 0;
            color: #888894;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 1.2em 0;
        }}
        th, td {{
            border: 1px solid var(--border-color);
            padding: 8px 14px;
            text-align: left;
        }}
        th {{
            background-color: var(--code-bg);
            font-weight: 600;
        }}
        hr {{
            border: none;
            border-top: 1px solid var(--border-color);
            margin: 2em 0;
        }}
        ul, ol {{
            padding-left: 28px;
            margin: 0.8em 0;
        }}
        li {{ margin-bottom: 0.3em; }}
        li.task-item {{
            list-style-type: none;
            margin-left: -14px;
            margin-bottom: 0.3em;
        }}
        li.task-item.checked {{
            color: #8e8e93;
        }}
        @media print {{
            body {{ padding: 0; background: white; color: black; }}
            .container {{ max-width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        {content}
    </div>
</body>
</html>
"""


def _convert_markdown_to_styled_html(
    note_title: str,
    markdown_content: str,
    dark_theme: bool = False,
) -> str:
    """Convert markdown text to styled HTML with modern vector SVG checkboxes.

    Replaces default Qt ballot box glyphs (U+2610 / U+2612) with Apple Notes-style
    clean rounded vector checkbox icons.
    """
    trimmed = markdown_content.lstrip()
    if not trimmed.startswith("# "):
        full_markdown = f"# {note_title}\n\n{markdown_content}"
    else:
        full_markdown = markdown_content

    doc = QTextDocument()
    doc.setMarkdown(full_markdown)
    html = doc.toHtml()

    # Remove Qt's default ballot box ::marker CSS rules
    html = re.sub(r"li\.(?:unchecked|checked)::marker\s*\{[^}]*\}", "", html)

    border_color = "#6c6c70" if dark_theme else "#8e8e93"
    dimmed_color = "#7c7c82" if dark_theme else "#8e8e93"

    svg_unchecked = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 16 16">'
        f'<rect x="1" y="1" width="14" height="14" rx="3.5" fill="none" stroke="{border_color}" stroke-width="1.8"/>'
        f"</svg>"
    )
    svg_checked = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 16 16">'
        '<rect x="1" y="1" width="14" height="14" rx="3.5" fill="#0a84ff" stroke="#0a84ff" stroke-width="1.8"/>'
        '<path d="M4.5 8.5L7 11L11.5 5.5" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>"
    )

    b64_unchecked = base64.b64encode(svg_unchecked.encode("utf-8")).decode("ascii")
    b64_checked = base64.b64encode(svg_checked.encode("utf-8")).decode("ascii")

    img_unchecked = f'<img src="data:image/svg+xml;base64,{b64_unchecked}" style="vertical-align: middle;"> '
    img_checked = f'<img src="data:image/svg+xml;base64,{b64_checked}" style="vertical-align: middle;"> '

    html = re.sub(
        r'<li class="unchecked"([^>]*)>',
        rf'<li class="task-item unchecked" style="list-style-type: none; margin-left: -12px; margin-bottom: 4px;">{img_unchecked}',
        html,
    )
    html = re.sub(
        r'<li class="checked"([^>]*)>',
        rf'<li class="task-item checked" style="list-style-type: none; margin-left: -12px; margin-bottom: 4px; color: {dimmed_color};">{img_checked}',
        html,
    )

    return html


def export_note_to_pdf(
    note_title: str,
    markdown_content: str,
    output_path: Path,
) -> bool:
    """Export note markdown to a high-DPI paginated PDF document.

    Args:
        note_title: The title of the note.
        markdown_content: The raw markdown content.
        output_path: Target destination path for the PDF file.

    Returns:
        True if PDF was successfully written, False otherwise.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        writer = QPdfWriter(str(output_path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(18.0, 18.0, 18.0, 18.0),
            QPageLayout.Unit.Millimeter,
        )
        writer.setPageLayout(layout)

        styled_html = _convert_markdown_to_styled_html(note_title, markdown_content, dark_theme=False)

        # Inject PDF_STYLE
        if "<style" in styled_html:
            styled_html = re.sub(r"(<style[^>]*>)", rf"\1\n{PDF_STYLE}\n", styled_html, count=1)
        else:
            styled_html = f"<html><head><style>{PDF_STYLE}</style></head><body>{styled_html}</body></html>"

        doc = QTextDocument()
        doc.setHtml(styled_html)
        doc.print(writer)
        return True
    except Exception as err:
        logger.error(f"Failed to export note to PDF: {err}")
        return False


def export_note_to_html(
    note_title: str,
    markdown_content: str,
    output_path: Path,
    dark_theme: bool = False,
) -> bool:
    """Export note markdown to a standalone, responsive HTML document.

    Args:
        note_title: The title of the note.
        markdown_content: The raw markdown content.
        output_path: Target destination path for the HTML file.
        dark_theme: Whether to export with modern dark styling.

    Returns:
        True if HTML was successfully written, False otherwise.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        styled_html = _convert_markdown_to_styled_html(note_title, markdown_content, dark_theme=dark_theme)

        # Extract inner body content from QTextDocument HTML
        start_tag = "<body"
        end_tag = "</body>"
        s_idx = styled_html.find(start_tag)
        if s_idx != -1:
            body_start = styled_html.find(">", s_idx) + 1
            e_idx = styled_html.find(end_tag)
            extracted_content = styled_html[body_start:e_idx] if e_idx != -1 else styled_html[body_start:]
        else:
            extracted_content = styled_html

        if dark_theme:
            bg_color = "#1e1e22"
            text_color = "#e2e2e8"
            heading_color = "#ffffff"
            code_bg = "#28282e"
            border_color = "#36363e"
        else:
            bg_color = "#ffffff"
            text_color = "#202024"
            heading_color = "#111114"
            code_bg = "#f5f5f8"
            border_color = "#e2e2e8"

        full_html = HTML_TEMPLATE.format(
            title=note_title,
            bg_color=bg_color,
            text_color=text_color,
            heading_color=heading_color,
            code_bg=code_bg,
            border_color=border_color,
            content=extracted_content,
        )

        output_path.write_text(full_html, encoding="utf-8")
        return True
    except Exception as err:
        logger.error(f"Failed to export note to HTML: {err}")
        return False

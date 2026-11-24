"""Markdown image detection, path resolution, cached rendering, and clipboard image saving."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import shutil
from typing import List, Optional, Set, Tuple
from urllib.parse import unquote

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QTextDocument

SUPPORTED_IMAGE_EXTENSIONS = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".svg",
})

# Matches standalone Markdown image lines: ![alt](path) or ![alt](<path with spaces> "title")
IMAGE_LINE_RE = re.compile(
    r'^\s*!\[([^\]]*)\]\(\s*(?:<([^>\n]+)>|([^\s)\n]+))(?:\s+(?:"[^"]*"|\'[^\']*\'))?\s*\)\s*$'
)


@dataclass(slots=True)
class ImageRegion:
    """Represents a single-line standalone Markdown image embed in a QTextDocument."""

    start_block: int
    end_block: int
    alt_text: str
    raw_src: str


def find_image_regions(
    doc: QTextDocument,
    excluded_blocks: Optional[Set[int]] = None,
) -> List[ImageRegion]:
    """Scan QTextDocument for standalone Markdown image lines outside excluded blocks."""
    regions: List[ImageRegion] = []
    block = doc.firstBlock()
    while block.isValid():
        bn = block.blockNumber()
        if excluded_blocks is None or bn not in excluded_blocks:
            text = block.text()
            if "![" in text:
                m = IMAGE_LINE_RE.match(text)
                if m:
                    alt_text = m.group(1).strip()
                    raw_src = (m.group(2) or m.group(3) or "").strip()
                    if raw_src:
                        regions.append(
                            ImageRegion(
                                start_block=bn,
                                end_block=bn,
                                alt_text=alt_text,
                                raw_src=raw_src,
                            )
                        )
        block = block.next()
    return regions


def resolve_image_path(
    raw_src: str,
    note_dir: Optional[Path] = None,
    root_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Resolve a Markdown image path relative to note_dir, root_dir, or absolute path."""
    cleaned = raw_src.strip()
    if not cleaned:
        return None
    lower = cleaned.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return None

    decoded = unquote(cleaned)
    candidate = Path(decoded)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None

    if note_dir is not None:
        rel_note = note_dir / candidate
        if rel_note.is_file():
            return rel_note

    if root_dir is not None:
        rel_root = root_dir / candidate
        if rel_root.is_file():
            return rel_root

    return None


class _ImagePixmapCache:
    """Bounded LRU cache for decoded local QPixmaps keyed by (path, mtime_ns, size)."""

    def __init__(self, max_entries: int = 48) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[Tuple[Path, int, int], QPixmap] = OrderedDict()

    def get(self, path: Optional[Path]) -> Optional[QPixmap]:
        if path is None:
            return None
        try:
            st = path.stat()
            key = (path, st.st_mtime_ns, st.st_size)
        except OSError:
            return None

        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached

        pm = QPixmap(str(path))
        if pm.isNull():
            return None

        # Cap decoded backing pixmap to 1600px on longest edge to keep RAM low
        max_dim = 1600
        if pm.width() > max_dim or pm.height() > max_dim:
            pm = pm.scaled(
                max_dim,
                max_dim,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        self._entries[key] = pm
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return pm

    def clear(self) -> None:
        self._entries.clear()


_IMAGE_CACHE = _ImagePixmapCache()


def get_cached_image_pixmap(
    raw_src: str,
    note_dir: Optional[Path] = None,
    root_dir: Optional[Path] = None,
) -> Optional[QPixmap]:
    """Resolve and return a cached QPixmap for a Markdown image reference, or None."""
    resolved = resolve_image_path(raw_src, note_dir=note_dir, root_dir=root_dir)
    return _IMAGE_CACHE.get(resolved)


def get_image_card_dimensions(
    pixmap: Optional[QPixmap],
    avail_w: float,
    ui_scale: float = 1.0,
) -> Tuple[float, float]:
    """Compute logical (width, height) for rendering an image preview card."""
    max_w = max(180.0, min(avail_w, round(680.0 * ui_scale)))
    max_h = round(460.0 * ui_scale)

    if pixmap is None or pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
        return min(max_w, round(360.0 * ui_scale)), round(48.0 * ui_scale)

    pw = float(pixmap.width())
    ph = float(pixmap.height())

    scale = 1.0
    if pw > max_w:
        scale = min(scale, max_w / pw)
    if ph * scale > max_h:
        scale = min(scale, max_h / ph)

    w = max(round(48.0 * ui_scale), round(pw * scale))
    h = max(round(36.0 * ui_scale), round(ph * scale))
    return float(w), float(h)


def render_image_card(
    painter: QPainter,
    rect: QRectF,
    pixmap: Optional[QPixmap],
    alt_text: str,
    raw_src: str,
    ui_scale: float = 1.0,
) -> None:
    """Paint a crisp rounded image preview or a subtle missing-image placeholder."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    radius = round(8.0 * ui_scale, 1)
    clip_path = QPainterPath()
    clip_path.addRoundedRect(rect, radius, radius)

    if pixmap is not None and not pixmap.isNull():
        painter.setClipPath(clip_path)
        painter.drawPixmap(rect, pixmap, QRectF(0.0, 0.0, float(pixmap.width()), float(pixmap.height())))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)
    else:
        painter.setPen(QPen(QColor("#3a3a40"), 1.0))
        painter.setBrush(QColor(36, 36, 40, 220))
        painter.drawRoundedRect(rect, radius, radius)
        painter.setPen(QColor("#8e8e93"))
        font = QFont(painter.font())
        font.setPointSize(max(9, int(round(10 * ui_scale))))
        painter.setFont(font)
        label = f"Image not found: {alt_text or raw_src}"
        painter.drawText(
            rect.adjusted(12.0, 0.0, -12.0, 0.0),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            label,
        )

    painter.restore()


def save_pasted_image(image: QImage, note_dir: Path) -> Optional[str]:
    """Save a clipboard QImage into `<note_dir>/images/` and return its relative Markdown path."""
    if image.isNull():
        return None
    images_dir = note_dir / "images"
    try:
        images_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = images_dir / f"pasted-{stamp}.png"
        counter = 1
        while candidate.exists():
            candidate = images_dir / f"pasted-{stamp}-{counter}.png"
            counter += 1
        if not image.save(str(candidate), "PNG"):
            return None
        return f"images/{candidate.name}"
    except (PermissionError, OSError):
        return None


def copy_pasted_image_file(src_file: Path, note_dir: Path) -> Optional[str]:
    """Copy a local image file into `<note_dir>/images/` and return its relative Markdown path."""
    if not src_file.is_file() or src_file.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        return None
    images_dir = note_dir / "images"
    try:
        images_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", src_file.stem).strip("-") or "image"
        ext = src_file.suffix.lower()
        candidate = images_dir / f"{safe_stem}{ext}"
        counter = 1
        while candidate.exists():
            candidate = images_dir / f"{safe_stem}-{counter}{ext}"
            counter += 1
        shutil.copy2(src_file, candidate)
        return f"images/{candidate.name}"
    except (PermissionError, OSError):
        return None

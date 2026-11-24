"""Syntax detection, background metadata caching, and vector rendering for YouTube video cards."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple
import urllib.error
import urllib.request

from PyQt6.QtCore import QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QTextDocument,
)

YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|v/)|youtu\.be/|youtube-nocookie\.com/embed/)([a-zA-Z0-9_-]{11})",
    re.IGNORECASE,
)

IFRAME_START_RE = re.compile(r"^\s*<iframe\b", re.IGNORECASE)
IFRAME_END_RE = re.compile(r"</iframe>", re.IGNORECASE)


@dataclass
class VideoRegion:
    """Represents a detected YouTube video card block in the editor."""

    start_block: int
    end_block: int
    video_id: str
    url: str
    title: str = "YouTube Video"
    author: str = "YouTube"


def extract_youtube_id(text: str) -> Optional[str]:
    """Extract an 11-character YouTube video ID from a URL or iframe string."""
    m = YOUTUBE_URL_RE.search(text)
    if m:
        return m.group(1)
    return None


def is_standalone_video_line(text: str) -> bool:
    """Check if a line of text represents a standalone YouTube video embed or URL."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.lower().startswith("<iframe") and ("youtube" in stripped.lower() or "youtu.be" in stripped.lower()):
        return True
    if not extract_youtube_id(stripped):
        return False
    if stripped.startswith("http://") or stripped.startswith("https://") or stripped.startswith("www."):
        return True
    if stripped.startswith("[") and stripped.endswith(")"):
        return True
    prefix_clean = re.sub(r"^(?:video|youtube|embed|watch)?\s*[:\-]\s*", "", stripped, flags=re.IGNORECASE)
    if prefix_clean.startswith("http://") or prefix_clean.startswith("https://") or prefix_clean.startswith("<iframe"):
        return True
    return False


def find_video_regions(doc: QTextDocument, excluded_blocks: Optional[Set[int]] = None) -> List[VideoRegion]:
    """Scan a QTextDocument for standalone YouTube links and <iframe> blocks."""
    regions: List[VideoRegion] = []
    excluded = excluded_blocks or set()
    b = doc.firstBlock()

    while b.isValid():
        i = b.blockNumber()
        if i in excluded:
            b = b.next()
            continue

        text = b.text()
        lower_t = text.lower()
        if "youtu" not in lower_t and "<iframe" not in lower_t:
            b = b.next()
            continue

        stripped = text.strip()

        # 1. Multiline or single-line <iframe>
        if "<iframe" in lower_t and IFRAME_START_RE.match(stripped):
            cur = b
            combined_lines = [stripped]
            closed = bool(IFRAME_END_RE.search(stripped))
            while not closed:
                nxt = cur.next()
                if not nxt.isValid():
                    break
                cur = nxt
                next_t = cur.text().strip()
                combined_lines.append(next_t)
                if IFRAME_END_RE.search(next_t):
                    closed = True
                    break

            combined_str = " ".join(combined_lines)
            if "youtube" in combined_str.lower() or "youtu.be" in combined_str.lower():
                vid = extract_youtube_id(combined_str)
                if vid:
                    regions.append(
                        VideoRegion(
                            start_block=i,
                            end_block=cur.blockNumber(),
                            video_id=vid,
                            url=f"https://www.youtube.com/watch?v={vid}",
                        )
                    )
                    b = cur.next()
                    continue

        # 2. Standalone URL or markdown link on a single block
        if is_standalone_video_line(stripped):
            vid = extract_youtube_id(stripped)
            if vid:
                regions.append(
                    VideoRegion(
                        start_block=i,
                        end_block=i,
                        video_id=vid,
                        url=f"https://www.youtube.com/watch?v={vid}",
                    )
                )
                b = b.next()
                continue

        b = b.next()

    return regions


class ThumbnailLoadSignals(QObject):
    """Signals for background video metadata and thumbnail loading."""

    loaded = pyqtSignal(str, str, str, str)  # video_id, thumb_file_path, title, author


class VideoMetadataWorker(QRunnable):
    """Background worker fetching YouTube oEmbed title and thumbnail asynchronously."""

    def __init__(self, video_id: str, cache_dir: Path, signals: ThumbnailLoadSignals) -> None:
        super().__init__()
        self.video_id = video_id
        self.cache_dir = cache_dir
        self.signals = signals

    def run(self) -> None:
        title = "YouTube Video"
        author = "YouTube"
        thumb_path = self.cache_dir / f"{self.video_id}.jpg"
        meta_path = self.cache_dir / f"{self.video_id}.json"

        # Check metadata cache
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    title = data.get("title", title)
                    author = data.get("author", author)
            except Exception:
                pass
        else:
            try:
                oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={self.video_id}&format=json"
                req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0 (MarkupNotes/1.0)"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    title = data.get("title", title)
                    author = data.get("author_name", author)
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump({"title": title, "author": author}, f)
            except Exception:
                pass

        # Check thumbnail cache or fetch from YouTube
        if not thumb_path.exists():
            try:
                thumb_url = f"https://i.ytimg.com/vi/{self.video_id}/hqdefault.jpg"
                req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0 (MarkupNotes/1.0)"})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    raw_data = resp.read()
                    if raw_data:
                        with open(thumb_path, "wb") as f:
                            f.write(raw_data)
            except Exception:
                pass

        try:
            self.signals.loaded.emit(
                self.video_id,
                str(thumb_path) if thumb_path.exists() else "",
                title,
                author,
            )
        except (RuntimeError, Exception):
            pass


class YouTubeCacheManager(QObject):
    """Manages thread-safe local caching and asynchronous fetching for YouTube previews."""

    thumbnail_ready = pyqtSignal(str)

    _instance: Optional["YouTubeCacheManager"] = None

    @classmethod
    def instance(cls) -> "YouTubeCacheManager":
        if cls._instance is None:
            cls._instance = YouTubeCacheManager()
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        self.cache_dir = Path.home() / ".cache" / "markup-notes" / "youtube"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._pixmap_cache: Dict[str, QPixmap] = {}
        self._metadata_cache: Dict[str, Tuple[str, str]] = {}
        self._pending_loads: Set[str] = set()
        self.signals = ThumbnailLoadSignals()
        self.signals.loaded.connect(self._on_loaded)

    def _on_loaded(self, video_id: str, thumb_path: str, title: str, author: str) -> None:
        self._pending_loads.discard(video_id)
        if thumb_path and os.path.exists(thumb_path):
            pix = QPixmap(thumb_path)
            if not pix.isNull():
                self._pixmap_cache[video_id] = pix
        if title:
            self._metadata_cache[video_id] = (title, author)
        self.thumbnail_ready.emit(video_id)

    def get_thumbnail(self, video_id: str) -> Optional[QPixmap]:
        """Return cached QPixmap if available, otherwise trigger background load."""
        if video_id in self._pixmap_cache:
            return self._pixmap_cache[video_id]

        disk_file = self.cache_dir / f"{video_id}.jpg"
        if disk_file.exists():
            pix = QPixmap(str(disk_file))
            if not pix.isNull():
                self._pixmap_cache[video_id] = pix
                return pix

        self._request_fetch(video_id)
        return None

    def get_metadata(self, video_id: str) -> Tuple[str, str]:
        """Return cached (title, author) if available, otherwise trigger background load."""
        if video_id in self._metadata_cache:
            return self._metadata_cache[video_id]

        disk_meta = self.cache_dir / f"{video_id}.json"
        if disk_meta.exists():
            try:
                with open(disk_meta, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    res = (data.get("title", "YouTube Video"), data.get("author", "YouTube"))
                    self._metadata_cache[video_id] = res
                    return res
            except Exception:
                pass

        self._request_fetch(video_id)
        return ("YouTube Video", "YouTube")

    def _request_fetch(self, video_id: str) -> None:
        if video_id in self._pending_loads:
            return
        self._pending_loads.add(video_id)
        worker = VideoMetadataWorker(video_id, self.cache_dir, self.signals)
        QThreadPool.globalInstance().start(worker)


def get_video_card_dimensions(available_w: float, ui_scale: float = 1.0) -> Tuple[float, float]:
    """Calculate responsive (card_width, card_height) for a 16:9 YouTube video card."""
    max_w = round(480.0 * ui_scale)
    card_w = max(240.0, min(float(max_w), float(available_w)))
    thumb_h = round((card_w * 9.0) / 16.0)
    info_h = round(46.0 * ui_scale)
    card_h = float(thumb_h + info_h)
    return card_w, card_h


def render_video_card(
    painter: QPainter,
    card_rect: QRectF,
    video_id: str,
    pixmap: Optional[QPixmap],
    title: str = "YouTube Video",
    author: str = "YouTube",
    is_hovered: bool = False,
    is_play_hovered: bool = False,
    ui_scale: float = 1.0,
) -> None:
    """Render an Apple Notes/Notion-style YouTube video card with thumbnail, play button, and title bar."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    corner_r = round(10.0 * ui_scale, 1)
    info_h = round(46.0 * ui_scale)
    thumb_h = max(20.0, card_rect.height() - info_h)

    # 1. Outer container clipping
    clip_path = QPainterPath()
    clip_path.addRoundedRect(card_rect, corner_r, corner_r)
    painter.setClipPath(clip_path)

    # Background
    painter.fillRect(card_rect, QColor("#1e1e24"))

    # 2. Thumbnail rendering
    thumb_rect = QRectF(card_rect.left(), card_rect.top(), card_rect.width(), thumb_h)
    if pixmap is not None and not pixmap.isNull():
        scaled_pix = pixmap.scaled(
            int(thumb_rect.width()),
            int(thumb_rect.height()),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        crop_x = max(0.0, (scaled_pix.width() - thumb_rect.width()) / 2.0)
        crop_y = max(0.0, (scaled_pix.height() - thumb_rect.height()) / 2.0)
        painter.drawPixmap(
            QPointF(thumb_rect.left(), thumb_rect.top()),
            scaled_pix,
            QRectF(crop_x, crop_y, thumb_rect.width(), thumb_rect.height()),
        )
    else:
        # Dark placeholder gradient when thumbnail is loading or offline
        p_grad = QLinearGradient(thumb_rect.left(), thumb_rect.top(), thumb_rect.left(), thumb_rect.bottom())
        p_grad.setColorAt(0.0, QColor("#282834"))
        p_grad.setColorAt(1.0, QColor("#1a1a22"))
        painter.fillRect(thumb_rect, p_grad)

    # Subtle gradient overlay for contrast
    v_grad = QLinearGradient(thumb_rect.left(), thumb_rect.top(), thumb_rect.left(), thumb_rect.bottom())
    v_grad.setColorAt(0.0, QColor(0, 0, 0, 30))
    v_grad.setColorAt(0.65, QColor(0, 0, 0, 40))
    v_grad.setColorAt(1.0, QColor(0, 0, 0, 180))
    painter.fillRect(thumb_rect, v_grad)

    # 3. Centered YouTube Vector Play Button
    btn_scale = 1.06 if (is_play_hovered or is_hovered) else 1.0
    btn_w = round(62.0 * ui_scale * btn_scale)
    btn_h = round(42.0 * ui_scale * btn_scale)
    btn_x = thumb_rect.left() + (thumb_rect.width() - btn_w) / 2.0
    btn_y = thumb_rect.top() + (thumb_h - btn_h) / 2.0
    play_rect = QRectF(btn_x, btn_y, btn_w, btn_h)

    painter.setPen(Qt.PenStyle.NoPen)
    btn_color = QColor("#ff0000") if (is_play_hovered or is_hovered) else QColor(255, 0, 0, 230)
    painter.setBrush(QBrush(btn_color))
    painter.drawRoundedRect(play_rect, round(12.0 * ui_scale), round(12.0 * ui_scale))

    # White play triangle
    tri_w = round(16.0 * ui_scale * btn_scale)
    tri_h = round(18.0 * ui_scale * btn_scale)
    tri_x = btn_x + (btn_w - tri_w) / 2.0 + round(2.0 * ui_scale)
    tri_y = btn_y + (btn_h - tri_h) / 2.0
    tri = QPolygonF([
        QPointF(tri_x, tri_y),
        QPointF(tri_x + tri_w, tri_y + tri_h / 2.0),
        QPointF(tri_x, tri_y + tri_h),
    ])
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawPolygon(tri)

    # 4. Bottom Info Bar
    info_rect = QRectF(card_rect.left(), card_rect.top() + thumb_h, card_rect.width(), info_h)
    painter.fillRect(info_rect, QColor("#1e1e24"))

    # Divider line
    painter.setPen(QPen(QColor("#2e2e38"), 1.0))
    painter.drawLine(info_rect.topLeft(), info_rect.topRight())

    # YouTube Red Mini Badge
    badge_w = round(26.0 * ui_scale)
    badge_h = round(18.0 * ui_scale)
    badge_x = info_rect.left() + round(14.0 * ui_scale)
    badge_y = info_rect.top() + (info_h - badge_h) / 2.0
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#ff0000")))
    painter.drawRoundedRect(QRectF(badge_x, badge_y, badge_w, badge_h), round(4.0 * ui_scale), round(4.0 * ui_scale))

    mini_tri = QPolygonF([
        QPointF(badge_x + round(10.0 * ui_scale), badge_y + round(5.0 * ui_scale)),
        QPointF(badge_x + round(17.5 * ui_scale), badge_y + round(9.0 * ui_scale)),
        QPointF(badge_x + round(10.0 * ui_scale), badge_y + round(13.0 * ui_scale)),
    ])
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawPolygon(mini_tri)

    # Title & Channel
    text_x = badge_x + badge_w + round(12.0 * ui_scale)
    max_text_w = max(50.0, info_rect.right() - text_x - round(80.0 * ui_scale))

    title_font = QFont("Cantarell", -1)
    title_font.setPixelSize(max(10, int(round(13 * ui_scale))))
    title_font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(title_font)
    painter.setPen(QColor("#f0f0f5"))

    fm_title = QFontMetrics(title_font)
    elided_title = fm_title.elidedText(title, Qt.TextElideMode.ElideRight, int(max_text_w))
    painter.drawText(QPointF(text_x, info_rect.top() + round(20.0 * ui_scale)), elided_title)

    author_font = QFont("Cantarell", -1)
    author_font.setPixelSize(max(9, int(round(11 * ui_scale))))
    painter.setFont(author_font)
    painter.setPen(QColor("#8e8e96"))
    author_text = f"{author} • YouTube" if author else "YouTube"
    painter.drawText(QPointF(text_x, info_rect.top() + round(37.0 * ui_scale)), author_text)

    # Watch external action label on right
    watch_font = QFont("Cantarell", -1)
    watch_font.setPixelSize(max(9, int(round(11 * ui_scale))))
    watch_font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(watch_font)
    painter.setPen(QColor("#0a84ff") if is_hovered else QColor("#8e8e96"))
    watch_rect = QRectF(info_rect.right() - round(74.0 * ui_scale), info_rect.top(), round(62.0 * ui_scale), info_h)
    painter.drawText(watch_rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), "Watch ↗")

    painter.restore()

    # 5. Outer Border
    painter.setPen(QPen(QColor("#0a84ff") if is_hovered else QColor("#383842"), 1.2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(card_rect, corner_r, corner_r)

"""Linux file-manager style natural sorting helpers for notes and folder trees."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from core.note import Note

SORT_NAME_ASC = "name_asc"
SORT_NAME_DESC = "name_desc"
SORT_NEWEST = "newest"
SORT_OLDEST = "oldest"

VALID_SORT_ORDERS = (
    SORT_NAME_ASC,
    SORT_NAME_DESC,
    SORT_NEWEST,
    SORT_OLDEST,
)
DEFAULT_SORT_ORDER = SORT_NAME_ASC

_NUMERIC_PART_RE = re.compile(r"(\d+)")


def normalize_sort_order(sort_order: Optional[str]) -> str:
    """Return a valid sort order constant, falling back to DEFAULT_SORT_ORDER."""
    if isinstance(sort_order, str) and sort_order in VALID_SORT_ORDERS:
        return sort_order
    return DEFAULT_SORT_ORDER


def natural_sort_key(text: str) -> Tuple[Tuple[Tuple[int, Union[int, str], int], ...], str]:
    """Compute a case-insensitive Linux natural sort key with deterministic tie-breaking.

    Matches Linux file manager defaults (e.g. 'apple' next to 'Apple', 'Note 2' before 'Note 10').
    """
    tokens: List[Tuple[int, Union[int, str], int]] = []
    for part in _NUMERIC_PART_RE.split(text.casefold()):
        if not part:
            continue
        if part.isdigit():
            tokens.append((0, int(part), len(part)))
        else:
            tokens.append((1, part, 0))
    return (tuple(tokens), text)


def sort_notes(notes: Sequence["Note"], sort_order: Optional[str] = None) -> List["Note"]:
    """Return notes sorted in memory according to the configured sort order."""
    mode = normalize_sort_order(sort_order)
    if mode == SORT_NAME_ASC:
        return sorted(
            notes,
            key=lambda n: (natural_sort_key(n.title), natural_sort_key(str(n.path))),
        )
    if mode == SORT_NAME_DESC:
        return sorted(
            notes,
            key=lambda n: (natural_sort_key(n.title), natural_sort_key(str(n.path))),
            reverse=True,
        )
    if mode == SORT_NEWEST:
        return sorted(
            notes,
            key=lambda n: (-n.modified_at, natural_sort_key(n.title), natural_sort_key(str(n.path))),
        )
    # SORT_OLDEST
    return sorted(
        notes,
        key=lambda n: (n.modified_at, natural_sort_key(n.title), natural_sort_key(str(n.path))),
    )


def _read_folder_mtime(path: Path) -> float:
    """Read directory modification timestamp safely, defaulting to 0.0 on error."""
    try:
        return path.stat().st_mtime
    except (FileNotFoundError, PermissionError, OSError):
        return 0.0


def sort_folders(
    folders: Sequence[Path],
    sort_order: Optional[str] = None,
) -> List[Path]:
    """Sort folders hierarchically so every nesting level obeys sort_order and parents precede children."""
    if not folders:
        return []

    mode = normalize_sort_order(sort_order)
    folder_set = set(folders)
    children_map: Dict[Optional[Path], List[Path]] = defaultdict(list)

    for folder in folder_set:
        parent_key: Optional[Path] = folder.parent if folder.parent in folder_set else None
        children_map[parent_key].append(folder)

    # Read filesystem mtime at most once per directory only for timestamp-based sort modes.
    mtime_map: Dict[Path, float] = {}
    if mode in (SORT_NEWEST, SORT_OLDEST):
        mtime_map = {folder: _read_folder_mtime(folder) for folder in folder_set}

    def _sort_siblings(siblings: List[Path]) -> None:
        if mode == SORT_NAME_ASC:
            siblings.sort(key=lambda p: (natural_sort_key(p.name), str(p)))
        elif mode == SORT_NAME_DESC:
            siblings.sort(key=lambda p: (natural_sort_key(p.name), str(p)), reverse=True)
        elif mode == SORT_NEWEST:
            siblings.sort(key=lambda p: (-mtime_map[p], natural_sort_key(p.name), str(p)))
        else:
            siblings.sort(key=lambda p: (mtime_map[p], natural_sort_key(p.name), str(p)))

    for sibling_list in children_map.values():
        _sort_siblings(sibling_list)

    ordered: List[Path] = []
    stack: List[Path] = list(reversed(children_map.get(None, [])))
    while stack:
        current = stack.pop()
        ordered.append(current)
        children = children_map.get(current, [])
        if children:
            stack.extend(reversed(children))

    return ordered

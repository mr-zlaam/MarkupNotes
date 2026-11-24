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


def _relative_item_key(path: Path, root_dir: Optional[Path]) -> str:
    """Return relative POSIX key from root_dir, or str(path) fallback."""
    if root_dir is not None:
        try:
            return path.relative_to(root_dir).as_posix()
        except ValueError:
            pass
    return str(path)


def sort_notes(
    notes: Sequence["Note"],
    sort_order: Optional[str] = None,
    pinned_keys: Optional[Sequence[str]] = None,
    root_dir: Optional[Path] = None,
) -> List["Note"]:
    """Return notes sorted with pinned notes first (latest pin on top) then `sort_order`."""
    mode = normalize_sort_order(sort_order)
    if mode == SORT_NAME_ASC:
        base_sorted = sorted(
            notes,
            key=lambda n: (natural_sort_key(n.title), natural_sort_key(str(n.path))),
        )
    elif mode == SORT_NAME_DESC:
        base_sorted = sorted(
            notes,
            key=lambda n: (natural_sort_key(n.title), natural_sort_key(str(n.path))),
            reverse=True,
        )
    elif mode == SORT_NEWEST:
        base_sorted = sorted(
            notes,
            key=lambda n: (-n.modified_at, natural_sort_key(n.title), natural_sort_key(str(n.path))),
        )
    else:
        base_sorted = sorted(
            notes,
            key=lambda n: (n.modified_at, natural_sort_key(n.title), natural_sort_key(str(n.path))),
        )

    if not pinned_keys:
        for n in base_sorted:
            n.is_pinned = False
        return base_sorted

    pin_rank = {key: idx for idx, key in enumerate(pinned_keys)}
    pinned_items: List[Tuple[int, "Note"]] = []
    unpinned_items: List["Note"] = []
    for note in base_sorted:
        key = _relative_item_key(note.path, root_dir)
        rank = pin_rank.get(key)
        if rank is not None:
            note.is_pinned = True
            pinned_items.append((rank, note))
        else:
            note.is_pinned = False
            unpinned_items.append(note)

    pinned_items.sort(key=lambda pair: pair[0])
    return [note for _, note in pinned_items] + unpinned_items


def _read_folder_mtime(path: Path) -> float:
    """Read directory modification timestamp safely, defaulting to 0.0 on error."""
    try:
        return path.stat().st_mtime
    except (FileNotFoundError, PermissionError, OSError):
        return 0.0


def sort_folders(
    folders: Sequence[Path],
    sort_order: Optional[str] = None,
    pinned_keys: Optional[Sequence[str]] = None,
    root_dir: Optional[Path] = None,
) -> List[Path]:
    """Sort folders hierarchically with pinned siblings first (latest pin on top) at every depth."""
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

    pin_rank = {key: idx for idx, key in enumerate(pinned_keys)} if pinned_keys else {}

    def _sort_siblings(siblings: List[Path]) -> None:
        if mode == SORT_NAME_ASC:
            siblings.sort(key=lambda p: (natural_sort_key(p.name), str(p)))
        elif mode == SORT_NAME_DESC:
            siblings.sort(key=lambda p: (natural_sort_key(p.name), str(p)), reverse=True)
        elif mode == SORT_NEWEST:
            siblings.sort(key=lambda p: (-mtime_map[p], natural_sort_key(p.name), str(p)))
        else:
            siblings.sort(key=lambda p: (mtime_map[p], natural_sort_key(p.name), str(p)))

        if pin_rank:
            pinned_sibs: List[Tuple[int, Path]] = []
            unpinned_sibs: List[Path] = []
            for p in siblings:
                rank = pin_rank.get(_relative_item_key(p, root_dir))
                if rank is not None:
                    pinned_sibs.append((rank, p))
                else:
                    unpinned_sibs.append(p)
            if pinned_sibs:
                pinned_sibs.sort(key=lambda pair: pair[0])
                siblings[:] = [p for _, p in pinned_sibs] + unpinned_sibs

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

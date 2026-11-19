"""File validation utilities for ensuring only valid Markdown and text files are opened."""

import os
from pathlib import Path
from typing import Optional, Set, Tuple

# Supported Markdown and plain text extensions
ALLOWED_EXTENSIONS: Set[str] = {
    ".md",
    ".markdown",
    ".mdown",
    ".mkd",
    ".txt",
    ".text",
    "",  # Files without extension (e.g., README, LICENSE, NOTES) are checked by content
}

# Maximum supported file size (50 MB) to protect against memory exhaustion
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024

# Maximum supported folder name length to avoid filesystem issues and sidebar truncation
MAX_FOLDER_NAME_LENGTH: int = 50

# Forbidden filesystem characters in folder names
INVALID_FILENAME_CHARS: Set[str] = set('/\\:*?"<>|\x00')

# Cross-platform / Windows reserved device names
RESERVED_DEVICE_NAMES: Set[str] = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}

# Chunk size for binary content probing
PROBE_CHUNK_SIZE: int = 8192


def validate_folder_name(name: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Validate a folder name for creation or renaming.

    Returns:
        A tuple of (is_valid, error_title, error_message).
        If is_valid is True, error_title and error_message are None.
    """
    if not name or not name.strip():
        return (
            False,
            "Invalid Folder Name",
            "Folder name cannot be empty. Please enter a valid name.",
        )

    stripped = name.strip()

    # 1. Reject hidden folders (starting with dot)
    if stripped.startswith("."):
        return (
            False,
            "Hidden Folder Not Allowed",
            "Folder names cannot start with a dot '.' because hidden folders are not displayed in the editor.",
        )

    # 2. Reject trailing dots
    if stripped.endswith("."):
        return (
            False,
            "Invalid Folder Name",
            "Folder names cannot end with a dot '.'.",
        )

    # 3. Reject overly long names
    if len(stripped) > MAX_FOLDER_NAME_LENGTH:
        return (
            False,
            "Folder Name Too Long",
            f"Folder name is too long ({len(stripped)} characters). Please keep it to {MAX_FOLDER_NAME_LENGTH} characters or fewer.",
        )

    # 4. Reject forbidden filesystem characters
    invalid_found = [c for c in stripped if c in INVALID_FILENAME_CHARS or ord(c) < 32]
    if invalid_found:
        unique_invalid = "".join(sorted(set(invalid_found)))
        return (
            False,
            "Invalid Characters",
            f"Folder name contains forbidden characters ({unique_invalid}). Names cannot contain slashes (/ \\), colons (:), quotes (\"), or wildcards (* ? < > |).",
        )

    # 5. Reject reserved device names
    if stripped.lower() in RESERVED_DEVICE_NAMES:
        return (
            False,
            "Reserved Name",
            f"'{stripped}' is a reserved system name and cannot be used as a folder name.",
        )

    return (True, None, None)


def validate_markdown_file(path: Path) -> Tuple[bool, Optional[str], Optional[str]]:
    """Validate whether a file is a safe, readable Markdown or plain text document.

    Returns:
        A tuple of (is_valid, error_title, error_message).
        If is_valid is True, error_title and error_message are None.
    """
    try:
        resolved_path = path.resolve()
    except Exception as resolve_err:
        return (
            False,
            "Invalid Path",
            f"The specified path could not be resolved: {resolve_err}",
        )

    # 1. Existence check
    if not resolved_path.exists():
        return (
            False,
            "File Not Found",
            f"The file '{resolved_path}' does not exist.",
        )

    # If it is a directory, it's valid for folder opening
    if resolved_path.is_dir():
        return (True, None, None)

    # 2. File type check (ensure it is a regular file)
    if not resolved_path.is_file():
        return (
            False,
            "Invalid File Type",
            f"'{resolved_path.name}' is a special system file (e.g., socket, device, or fifo) and cannot be opened.",
        )

    # 3. File extension check
    suffix = resolved_path.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return (
            False,
            "Unsupported File Format",
            f"Markup Notes only supports Markdown and plain text files (.md, .markdown, .txt).\n\n"
            f"Detected file type: '{suffix if suffix else 'Unknown'}'",
        )

    # 4. File size check
    try:
        size_bytes = resolved_path.stat().st_size
    except (FileNotFoundError, PermissionError) as stat_err:
        return (
            False,
            "Permission Denied",
            f"Unable to access file metadata for '{resolved_path.name}': {stat_err}",
        )

    if size_bytes > MAX_FILE_SIZE_BYTES:
        size_mb = size_bytes / (1024 * 1024)
        return (
            False,
            "File Too Large",
            f"The file '{resolved_path.name}' is {size_mb:.1f} MB, which exceeds the 50 MB limit.",
        )

    # 5. Read permission & binary content probe
    try:
        with open(resolved_path, "rb") as f:
            chunk = f.read(PROBE_CHUNK_SIZE)

        # Check for null bytes (a standard indicator of binary files like PDF, PNG, ELF, ZIP)
        if b"\x00" in chunk:
            return (
                False,
                "Binary File Detected",
                f"The file '{resolved_path.name}' appears to be a binary file, not a plain text Markdown document.\n\n"
                "Opening was blocked to prevent corruption or unexpected behavior.",
            )

        # Verify UTF-8 / UTF-8-BOM decodability
        try:
            chunk.decode("utf-8")
        except UnicodeDecodeError:
            try:
                chunk.decode("utf-8-sig")
            except UnicodeDecodeError:
                return (
                    False,
                    "Encoding Error",
                    f"The file '{resolved_path.name}' could not be decoded as UTF-8 text.\n\n"
                    "Markup Notes requires standard UTF-8 text encoding.",
                )

    except PermissionError:
        return (
            False,
            "Permission Denied",
            f"You do not have permission to read '{resolved_path.name}'.",
        )
    except OSError as os_err:
        return (
            False,
            "Read Error",
            f"An error occurred while reading '{resolved_path.name}': {os_err}",
        )

    return (True, None, None)

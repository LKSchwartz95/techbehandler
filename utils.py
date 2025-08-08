import os
import re


def sanitize_run_name(run_name: str) -> str:
    """Sanitize a run name for safe filesystem usage.

    Replaces path separators and disallows path traversal or dangerous
    characters. Only alphanumeric characters, dashes, underscores and
    dots are preserved; everything else is converted to underscores.

    Parameters
    ----------
    run_name: str
        Proposed name of a run.

    Returns
    -------
    str
        Sanitized run name safe for directory creation.

    Raises
    ------
    ValueError
        If the provided name resolves to an empty string or contains
        path traversal components.
    """
    if run_name is None:
        raise ValueError("run_name cannot be None")

    # Replace path separators with underscores.
    sanitized = run_name.replace(os.sep, "_")
    if os.altsep:
        sanitized = sanitized.replace(os.altsep, "_")

    # Replace any character not explicitly allowed.
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", sanitized)

    # Reject names that could traverse directories or are empty.
    if sanitized in ("", ".", "..") or ".." in sanitized:
        raise ValueError(f"Invalid run name: {run_name!r}")

    return sanitized

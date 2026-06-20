"""Balancelab project file (.ballab) helpers.

A project file is a zip archive that bundles a ``project.json`` manifest with
any embedded data files (recordings / loaded trials) under ``data/``. This
keeps a project self-contained: opening it on another machine restores the
full session without depending on the original CSV/C3D files.
"""

import io
import json
import os
import tempfile
import zipfile

PROJECT_EXT = ".ballab"
PROJECT_FILTER = f"Balancelab Project (*{PROJECT_EXT})"
MANIFEST_NAME = "project.json"


def save_project(path, manifest, files=None):
    """Write a project archive.

    Args:
        path: destination path (``.ballab`` appended if missing).
        manifest: JSON-serializable dict describing the session.
        files: optional dict mapping archive name (e.g. ``"data/0.csv"``) to
            ``bytes`` content to embed.
    """
    if not path.lower().endswith(PROJECT_EXT):
        path += PROJECT_EXT
    files = files or {}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for arcname, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8-sig")
            archive.writestr(arcname, content)
    return path


def load_project(path):
    """Read a project archive.

    Returns a tuple ``(manifest, datadir)`` where ``datadir`` is a temporary
    directory holding the extracted embedded files (or ``None`` if there were
    none). The caller may read embedded files via ``os.path.join(datadir, ...)``.
    """
    with zipfile.ZipFile(path, "r") as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        names = [n for n in archive.namelist() if n != MANIFEST_NAME and not n.endswith("/")]
        if not names:
            return manifest, None
        datadir = tempfile.mkdtemp(prefix="ballab_proj_")
        for name in names:
            target = os.path.join(datadir, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(archive.read(name))
    return manifest, datadir


def read_manifest(path):
    """Return just the manifest dict without extracting data files."""
    with zipfile.ZipFile(path, "r") as archive:
        return json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))

"""Immutable raw snapshots with provenance (charter: shared core collector contract).

Every downloaded file lands at raw/<source>/<YYYY-MM-DD>/<filename> with a manifest
holding URL, sha256, byte size and retrieval time. Snapshots are never overwritten.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def register_snapshot(raw_root: str | Path, source: str, file_path: str | Path, url: str,
                      retrieved_at: str | None = None) -> dict:
    """Copy an already-downloaded file into the snapshot store and write its manifest."""
    file_path = Path(file_path)
    retrieved_at = retrieved_at or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    day = retrieved_at[:10]
    dest_dir = Path(raw_root) / source / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file_path.name
    if dest.exists():
        if sha256_file(dest) != sha256_file(file_path):
            raise FileExistsError(f"{dest} exists with different content; snapshots are immutable")
    else:
        shutil.copy2(file_path, dest)
    digest = sha256_file(dest)
    manifest = {
        "source": source,
        "url": url,
        "file": dest.name,
        "sha256": digest,
        "bytes": dest.stat().st_size,
        "retrieved_at": retrieved_at,
        "source_id": f"{source}:{day}:{digest[:12]}",
    }
    (dest_dir / (dest.name + ".manifest.json")).write_text(json.dumps(manifest, indent=2))
    return manifest

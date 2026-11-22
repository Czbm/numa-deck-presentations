"""File-only recovery and autosave service for NUMA Deck Presentations.

This module deliberately has no Qt dependency. The window owns user prompts;
this service owns paths, atomic writes, hashes, retention and inspection.
"""

import hashlib
import json
import os
import time
from pathlib import Path


class RecoveryService:
    def __init__(self, root=None, retention_days=3):
        self.root = Path(root) if root else self.autosave_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention_days = int(retention_days)

    @staticmethod
    def autosave_root():
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NUMA Deck Presentations" / "autosaves"

    def paths_for_document(self, path):
        normalized = os.path.abspath(path) if path else ""
        if not normalized:
            return None, None
        key = hashlib.sha256(os.path.normcase(normalized).encode("utf-8")).hexdigest()
        return self.root / f"{key}.md", self.root / f"{key}.json"

    @staticmethod
    def content_hash(content):
        return hashlib.sha256((content or "").encode("utf-8")).hexdigest()

    def purge_expired(self):
        cutoff = time.time() - (self.retention_days * 24 * 60 * 60)
        removed = 0
        known_backups = set()
        for meta_path in self.root.glob("*.json"):
            backup_path = meta_path.with_suffix(".md")
            known_backups.add(backup_path.name)
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                created_at = float(metadata.get("created_at", meta_path.stat().st_mtime))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                created_at = meta_path.stat().st_mtime if meta_path.exists() else 0
            if backup_path.is_file():
                original_path = metadata.get("original_path") if isinstance(metadata, dict) else None
                try:
                    if original_path and Path(original_path).is_file():
                        original_text = Path(original_path).read_text(encoding="utf-8")
                        backup_text = backup_path.read_text(encoding="utf-8")
                        if original_text == backup_text:
                            removed += self._remove_candidates(meta_path, backup_path)
                            continue
                except (OSError, UnicodeError):
                    pass
            if created_at and created_at < cutoff:
                removed += self._remove_candidates(meta_path, backup_path)

        for backup_path in self.root.glob("*.md"):
            if backup_path.name in known_backups:
                continue
            try:
                if backup_path.stat().st_mtime < cutoff:
                    backup_path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue

        for temporary in self.root.glob("*.tmp"):
            try:
                if temporary.stat().st_mtime < cutoff:
                    temporary.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed

    @staticmethod
    def _remove_candidates(*paths):
        removed = 0
        for path in paths:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
        return removed

    def write_recovery_copy(self, path, content, clean_snapshot=True):
        if not path:
            return False
        backup_path, meta_path = self.paths_for_document(path)
        if backup_path is None:
            return False
        content = content or ""
        try:
            original = Path(path)
            temporary = backup_path.with_name(backup_path.name + ".tmp")
            temporary.write_text(content, encoding="utf-8", newline="")
            temporary.replace(backup_path)
            metadata = {
                "original_path": os.path.abspath(path),
                "backup_path": str(backup_path),
                "created_at": time.time(),
                "original_mtime_ns": original.stat().st_mtime_ns if original.is_file() else None,
                "content_sha256": self.content_hash(content),
                "content_bytes": len(content.encode("utf-8")),
                "clean_snapshot": bool(clean_snapshot),
            }
            meta_temporary = meta_path.with_name(meta_path.name + ".tmp")
            meta_temporary.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            meta_temporary.replace(meta_path)
            return True
        except (OSError, UnicodeError):
            return False

    def write_autosave(self, path, content):
        if not path:
            return False
        content = content or ""
        try:
            original = Path(path)
            if original.is_file() and original.read_text(encoding="utf-8") == content:
                # A previous recovery copy may remain after the user reverted
                # the document. A clean document must have no recovery pair.
                backup_path, meta_path = self.paths_for_document(path)
                self._remove_candidates(backup_path, meta_path)
                return False
        except (OSError, UnicodeError):
            pass
        return self.write_recovery_copy(path, content, clean_snapshot=False)

    def refresh_clean_backups(self, sources):
        """Remove recovery copies for sources that are being closed cleanly."""
        seen = set()
        removed = 0
        for path, _ in sources:
            if not path:
                continue
            normalized = os.path.abspath(path)
            key = os.path.normcase(normalized)
            if key in seen:
                continue
            seen.add(key)
            backup_path, meta_path = self.paths_for_document(normalized)
            removed += self._remove_candidates(backup_path, meta_path)
        return removed

    def inspect(self, path):
        """Return a verified recovery candidate, or None when unavailable."""
        normalized = os.path.abspath(path)
        backup_path, meta_path = self.paths_for_document(normalized)
        if not backup_path or not meta_path or not backup_path.is_file() or not meta_path.is_file():
            return None
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        backup_text = backup_path.read_text(encoding="utf-8")
        backup_hash = self.content_hash(backup_text)
        if metadata.get("content_sha256") != backup_hash:
            return {
                "valid": False,
                "path": normalized,
                "backup_path": str(backup_path),
                "meta_path": str(meta_path),
                "backup_hash": backup_hash,
                "expected_hash": metadata.get("content_sha256"),
            }
        original = Path(normalized)
        original_text = original.read_text(encoding="utf-8") if original.is_file() else ""
        return {
            "valid": True,
            "path": normalized,
            "backup_path": str(backup_path),
            "meta_path": str(meta_path),
            "metadata": metadata,
            "backup_text": backup_text,
            "original_text": original_text,
            "backup_hash": backup_hash,
            "original_hash": self.content_hash(original_text),
            "backup_is_newer": backup_path.stat().st_mtime_ns > (original.stat().st_mtime_ns if original.is_file() else 0),
            "differs": backup_text != original_text,
        }

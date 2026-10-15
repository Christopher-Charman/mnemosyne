"""Owner-scoped vault note reader. No review authority, DB writes, or sync."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
import stat
from pathlib import Path
from mnemosyne.integrations.owned_architecture_bridge import AdmissionError
from mnemosyne.integrations.owned_reviewed_source_preview import SourceRead

MAX_NOTE = 65536
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK

def _check_owner(st: os.stat_result, uid: int, *, directory: bool) -> None:
    valid = stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode)
    if not valid or st.st_uid != uid or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise AdmissionError("vault owner/type/mode mismatch")

def _parts(ref: str) -> list[str]:
    if not isinstance(ref, str) or not ref.startswith("obsidian:") or len(ref)>512:
        raise AdmissionError("invalid Obsidian source reference")
    parts=ref[len("obsidian:"):].split("/")
    if (len(parts)>32 or not parts[-1].endswith(".md")
        or any(not p or p in (".","..") or p.startswith(".") or chr(92) in p
               or any(ord(c)<33 for c in p) for p in parts)):
        raise AdmissionError("noncanonical vault path")
    return parts

def read_vault_note(ref: str, *, vault_root: Path, owner_uid: int) -> SourceRead:
    """A source snapshot, not an authenticated reviewer approval."""
    if type(owner_uid) is not int or owner_uid<0:
        raise AdmissionError("explicit filesystem owner required")
    parts=_parts(ref)
    folder=None
    note=None
    try:
        folder=os.open(os.fspath(vault_root),DIR_FLAGS)
        _check_owner(os.fstat(folder),owner_uid,directory=True)
        for name in parts[:-1]:
            newer=os.open(name,DIR_FLAGS,dir_fd=folder)
            try:
                _check_owner(os.fstat(newer),owner_uid,directory=True)
            except BaseException:
                os.close(newer)
                raise
            os.close(folder)
            folder=newer
        note=os.open(parts[-1],FILE_FLAGS,dir_fd=folder)
        before=os.fstat(note)
        _check_owner(before,owner_uid,directory=False)
        if not 1<=before.st_size<=MAX_NOTE or before.st_nlink != 1:
            raise AdmissionError("oversize, empty, or linked note")
        payload=os.read(note,MAX_NOTE+1)
        after=os.fstat(note)
        def stamp(s):
            return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode)
        if len(payload)!=before.st_size or stamp(before)!=stamp(after):
            raise AdmissionError("note changed during read")
        try:
            payload.decode("utf-8")
        except UnicodeError:
            raise AdmissionError("non-UTF8 note") from None
        return SourceRead(ref=ref,version="sha256:"+hashlib.sha256(payload).hexdigest(),
            raw=payload,observed_at=datetime.now(timezone.utc).replace(microsecond=0)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))
    except (OSError,TypeError,ValueError):
        raise AdmissionError("trusted vault source read denied") from None
    finally:
        if note is not None:os.close(note)
        if folder is not None:os.close(folder)

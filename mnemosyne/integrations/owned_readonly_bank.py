"""Strictly read-only, owner-configured SQLite recall for reviewed memory projections.

Uses an immutable connection and fails closed if a pending WAL exists. Never
constructs Mnemosyne/BeamMemory or increments recall counters.
"""
from __future__ import annotations
import json
import hashlib
import hmac
import os
import re
import sqlite3
import pathlib
from urllib.parse import quote

_MAX_SCAN = 256
_MAX_CONTENT = 8192
_TOKEN = re.compile(r"[a-z0-9_]{3,}", re.IGNORECASE)

class ImmutableRecallError(ValueError):
    pass

def recall_owner_bank(query: str, limit: int) -> list[dict]:
    if not isinstance(query, str) or type(limit) is not int or not 1 <= limit <= 5:
        raise ImmutableRecallError("invalid query bound")
    root = os.environ.get("MNEMOSYNE_OWNER_BANK_DB", "")
    expected_uid = os.environ.get("MNEMOSYNE_OWNER_UID", "")
    if not root or not expected_uid.isdecimal() or os.getuid() != int(expected_uid):
        raise ImmutableRecallError("owner bank and identity not explicitly configured")
    file = pathlib.Path(root)
    if file.is_symlink() or not file.is_file() or file.stat().st_uid != int(expected_uid):
        raise ImmutableRecallError("owner bank not a regular owned file")
    if (file.parent / (file.name + "-wal")).exists() and (file.parent / (file.name + "-wal")).stat().st_size:
        raise ImmutableRecallError("uncheckpointed WAL prohibits immutable reads")
    uri = "file:" + quote(str(file.resolve(strict=True)), safe="/") + "?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1)
        connection.execute("PRAGMA query_only=ON")
        rows = connection.execute(
            "SELECT w.id,w.content,w.source,w.scope,w.metadata_json,r.record_id,r.verification_method,r.fingerprint "
            "FROM working_memory AS w "
            "INNER JOIN owned_architecture_ingest_receipts AS r ON r.memory_id=w.id "
            "WHERE w.source='owned-architecture-projection' "
            "AND w.superseded_by IS NULL "
            "AND (w.valid_until IS NULL OR julianday(w.valid_until) > julianday('now')) "
            "AND r.bank='architecture' "
            "ORDER BY w.importance DESC,w.id ASC LIMIT ?", (_MAX_SCAN,)
        ).fetchall()
    except sqlite3.DatabaseError as ex:
        raise ImmutableRecallError("read-only bank schema/transaction unavailable") from None
    finally:
        if "connection" in locals():
            connection.close()

    tokens = set(_TOKEN.findall(query.lower()))
    matches = []
    for _id, content, origin, scope, raw_meta, rid, receipt_method, fingerprint in rows:
        if not isinstance(content, str) or len(content.encode("utf-8")) > _MAX_CONTENT:
            continue
        try:
            meta = json.loads(raw_meta)
        except (ValueError, TypeError):
            continue
        if (not isinstance(meta, dict)
            or meta.get("record_id") != rid
            or meta.get("authority") != "DERIVED_CONTEXT_ONLY"
            or meta.get("verified_source") is not True
            or meta.get("verification_method") != "PINNED_LOCAL_GIT_BLOB"
            or receipt_method != "PINNED_LOCAL_GIT_BLOB"
            or meta.get("bank") != "architecture"
            or meta.get("domain") != "shared-architecture"
            or meta.get("review_state") != "reviewed_candidate"
            or meta.get("classification") != "architecture_internal"
            or not isinstance(meta.get("source"), dict)):
            continue
        source = meta["source"]
        if (not isinstance(source.get("ref"), str)
            or not source["ref"].startswith("git:")
            or not isinstance(source.get("version"), str)
            or not re.fullmatch("[0-9a-f]{40}", source["version"])):
            continue
        source_hash = source.get("sha256")
        excerpt_hash = source.get("content_sha256")
        if (not isinstance(source_hash,str) or not re.fullmatch("[0-9a-f]{64}",source_hash)
            or not isinstance(excerpt_hash,str)
            or not hmac.compare_digest(excerpt_hash,hashlib.sha256(content.encode("utf-8")).hexdigest())
            or not isinstance(fingerprint,str)
            or not re.fullmatch("[0-9a-f]{64}",fingerprint)):
            continue
        # Reconstruct pre-ingestion projection and match its committed receipt.
        prior_meta=dict(meta)
        prior_meta["verified_source"]=False
        prior_meta.pop("verification_method",None)
        original={"content":content,"source":origin,"scope":scope,"metadata":prior_meta}
        digest=hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False,
                         separators=(",",":")).encode("utf-8")).hexdigest()
        if not hmac.compare_digest(digest,fingerprint):
            continue
        value = content.lower()
        score = sum(1 for token in tokens if token in value)
        if score == 0:
            continue
        matches.append((score, rid, {
            "content": content, "source": origin, "metadata": meta
        }))
    matches.sort(key=lambda x: (-x[0], x[1]))
    return [record for _,_,record in matches[:limit]]

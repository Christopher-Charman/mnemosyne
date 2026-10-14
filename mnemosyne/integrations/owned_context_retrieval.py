"""Bounded local historical + Mnemosyne context retrieval.

Historical context uses the existing user-owned read-only reader, not a new
archive DB connection. Mnemosyne memory is read only. No ingestion, network
listener, source mutation, or automatic agent injection occurs.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from mnemosyne.core.memory import Mnemosyne

SCHEMA = "owned-mnemosyne-context-request-v1"
RESULT_SCHEMA = "owned-mnemosyne-context-v1"
READER = Path("/home/storage/781/4477781/user/webapp/bin/chatgpt-owned-context-reader")
REQUEST_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{7,127}$")
MAX_BYTES = 160000
MAX_TEXT = 1800

class ContextBoundaryError(ValueError):
    pass

def validate(request: Any):
    if not isinstance(request, dict) or set(request) != {
        "schema", "request_id", "query", "since", "until", "limit"
    } or request["schema"] != SCHEMA:
        raise ContextBoundaryError("invalid context request")
    rid, query, count = request["request_id"], request["query"], request["limit"]
    if not isinstance(rid, str) or not REQUEST_ID.fullmatch(rid):
        raise ContextBoundaryError("invalid request identity")
    if not isinstance(query, str) or not 1 <= len(query) <= 256:
        raise ContextBoundaryError("invalid query")
    if any(ord(char) < 32 and char not in "\t\n" for char in query):
        raise ContextBoundaryError("invalid query control character")
    if type(count) is not int or not 1 <= count <= 5:
        raise ContextBoundaryError("result count not admitted")
    if not isinstance(request["since"], str) or not isinstance(request["until"], str):
        raise ContextBoundaryError("invalid date type")
    try:
        since = dt.date.fromisoformat(request["since"])
        until = dt.date.fromisoformat(request["until"])
    except ValueError:
        raise ContextBoundaryError("invalid date") from None
    if since > until or (until - since).days > 100:
        raise ContextBoundaryError("window outside 100-day bound")
    return rid, query, since.isoformat(), until.isoformat(), count

def invoke_owned_reader(rid, query, since, until, count, reader=READER):
    if not reader.is_file() or reader.is_symlink() or not os.access(reader, os.X_OK):
        raise ContextBoundaryError("owned historical reader not admitted")
    request = {
        "schema": "chatgpt-owned-readonly-v1",
        "request_id": rid,
        "target": "runtime:fasthost.powerpc_darwin_org",
        "tool": "session_context",
        "arguments": {"task": query, "since": since, "until": until, "limit": count},
    }
    body = json.dumps(request, separators=(",", ":"), sort_keys=True)
    if len(body.encode("utf-8")) > 4096:
        raise ContextBoundaryError("history request too large")
    try:
        process = subprocess.run(
            [str(reader)], input=body, text=True, capture_output=True,
            timeout=27, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ContextBoundaryError("owned historical reader unavailable") from None
    if process.returncode or len(process.stdout.encode("utf-8")) > MAX_BYTES:
        raise ContextBoundaryError("historical reader failed or exceeded bound")
    try:
        receipt = json.loads(process.stdout)
    except ValueError:
        raise ContextBoundaryError("malformed reader receipt") from None
    if (not isinstance(receipt, dict)
        or receipt.get("request_id") != rid
        or receipt.get("state") != "EXECUTED_READ_ONLY"
        or receipt.get("return_code") != 0):
        raise ContextBoundaryError("historical reader identity or effect mismatch")
    packet = receipt.get("output")
    if (not isinstance(packet, dict)
        or packet.get("schema") != "owned-session-context-v1"
        or packet.get("state") != "HISTORICAL_EVIDENCE_ONLY"
        or packet.get("automatic_session_injection") is not False
        or packet.get("instructions_from_archive_authoritative") is not False
        or packet.get("current_library_verified") is not False
        or packet.get("live_destination_verified") is not False
        or not isinstance(packet.get("records"), list)
        or len(packet["records"]) > count):
        raise ContextBoundaryError("historical packet exceeds provenance boundary")
    return packet

def _historical(packet, limit):
    if (not isinstance(packet, dict)
        or packet.get("schema") != "owned-session-context-v1"
        or packet.get("state") != "HISTORICAL_EVIDENCE_ONLY"
        or not isinstance(packet.get("records"), list)
        or len(packet["records"]) > limit):
        raise ContextBoundaryError("unverified historical record packet")
    records = []
    for row in packet["records"]:
        if (not isinstance(row, dict)
            or row.get("role") not in ("user", "assistant")
            or not isinstance(row.get("message_id"), str) or not row["message_id"]
            or not isinstance(row.get("conversation_id"), str) or not row["conversation_id"]
            or not isinstance(row.get("text"), str)):
            raise ContextBoundaryError("historical record is not attributable")
        refs = row.get("evidence_refs", [])
        if not isinstance(refs, list) or len(refs) > 20:
            raise ContextBoundaryError("historical references exceed bound")
        if any(not isinstance(ref, str) or len(ref) > 300 for ref in refs):
            raise ContextBoundaryError("invalid historical evidence reference")
        content = row["text"]
        records.append({
            "kind": "HISTORICAL_MESSAGE", "authority": "HISTORICAL_EVIDENCE_ONLY",
            "role": row["role"], "authorship_verified": False,
            "message_id": row["message_id"], "conversation_id": row["conversation_id"],
            "date": row.get("date"), "text": content[:MAX_TEXT],
            "text_truncated": bool(row.get("text_truncated")) or len(content) > MAX_TEXT,
            "source_sha256": row.get("sha256"), "evidence_refs": refs,
        })
    return records

def _derived(memory, query, limit):
    found = memory.recall(query, top_k=limit)
    if not isinstance(found, list):
        raise ContextBoundaryError("invalid memory recall result")
    records = []
    for row in found[:limit]:
        if not isinstance(row, dict) or row.get("source") != "owned-architecture-projection":
            continue
        meta = row.get("metadata")
        if isinstance(meta, str):
            try: meta = json.loads(meta)
            except ValueError: continue
        if (not isinstance(meta, dict)
            or meta.get("authority") != "DERIVED_CONTEXT_ONLY"
            or meta.get("verified_source") is not True
            or meta.get("verification_method") != "PINNED_LOCAL_GIT_BLOB"
            or meta.get("domain") != "shared-architecture"
            or meta.get("bank") != "architecture"):
            continue
        content, evidence = row.get("content"), meta.get("source")
        if not isinstance(content, str) or not isinstance(evidence, dict):
            continue
        records.append({
            "kind": "VERIFIED_DERIVED_MEMORY", "authority": "DERIVED_CONTEXT_ONLY",
            "record_id": meta.get("record_id"), "text": content[:MAX_TEXT],
            "text_truncated": len(content) > MAX_TEXT,
            "source_ref": evidence.get("ref"), "source_version": evidence.get("version"),
        })
    return records

def build_context(request, *, memory=None, historical_packet=None):
    rid, query, since, until, count = validate(request)
    if memory is None:
        memory = Mnemosyne(bank="architecture", session_id="owned-mnemosyne-context")
    if getattr(memory, "bank", None) != "architecture":
        raise ContextBoundaryError("cross-bank context denied")
    packet = historical_packet
    if packet is None:
        packet = invoke_owned_reader(rid, query, since, until, count)
    historical = _historical(packet, count)
    derived = _derived(memory, query, count)
    return {
        "schema": RESULT_SCHEMA, "request_id": rid, "state": "READ_ONLY_CONTEXT",
        "runtime_id": "fasthost.powerpc_darwin_org", "domain": "shared-architecture",
        "historical_evidence_class": "HISTORICAL_MESSAGES_NOT_CURRENT_AUTHORITY",
        "derived_memory_authority": "DERIVED_CONTEXT_ONLY",
        "archive_index_at": packet.get("archive_index_generated_at"),
        "history_gap_after_index": packet.get("history_gap_after_index"),
        "current_project_authority_verified": False, "automatic_agent_injection": False,
        "memory_ingestion": False, "sync_enabled": False,
        "historical": historical, "mnemosyne": derived,
        "required_next_evidence": ["CURRENT_DIRECT_SOURCE_READBACK",
                                   "EXACT_RUNTIME_AUTHORITY", "POST_INDEX_CHAT_COVERAGE"],
    }

def main():
    try:
        raw = sys.stdin.buffer.read(4097)
        if len(raw) > 4096 or os.getuid() != 2257347:
            raise ContextBoundaryError("request admission failed")
        result = build_context(json.loads(raw.decode("utf-8")))
        output = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(output.encode("utf-8")) > MAX_BYTES:
            raise ContextBoundaryError("response exceeds maximum size")
    except (ContextBoundaryError, OSError, ValueError, TypeError):
        print(json.dumps({"schema": RESULT_SCHEMA, "state": "BLOCKED", "reason": "ADMISSION_FAILED"}))
        return 2
    print(output)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

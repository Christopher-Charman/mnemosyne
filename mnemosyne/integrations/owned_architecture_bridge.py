"""Fail-closed, read-only projection planning for user-owned architecture evidence.

This module NEVER imports, persists, synchronises, or promotes memory by itself.
An owning caller must verify the canonical source and separately admit any
subsequent mutation. Public code must never contain private archive payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "owned-architecture-memory-v1"
DOMAIN = "shared-architecture"
KINDS = frozenset(
    {"fact", "decision", "hypothesis", "method", "test", "outcome",
     "correction", "lesson", "task_frontier"}
)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_SOURCE_PREFIXES = ("library:/", "git:", "archive:", "runtime:")
_MAX_CONTENT = 8192
_MAX_RECORDS = 256
_MAX_LINE = 32768
_SOURCE_TYPES = {
    "library:/": "canonical_document",
    "git:": "git_blob",
    "archive:": "archive_excerpt",
    "runtime:": "runtime_receipt",
}
_UTC_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)


class AdmissionError(ValueError):
    """Record is not safe to project as derived, untrusted context."""


@dataclass(frozen=True)
class ProjectionPlan:
    bank: str
    domain: str
    digest: str
    memories: tuple[dict[str, Any], ...]

    def receipt(self) -> dict[str, Any]:
        """Return a data-minimised receipt; no memory text or source payload."""
        return {
            "schema": "owned-architecture-memory-plan-v1",
            "mode": "READ_ONLY_PREVIEW",
            "authority": "DERIVED_CONTEXT_NOT_SOURCE_OF_TRUTH",
            "writes": 0,
            "sync_enabled": False,
            "bank": self.bank,
            "domain": self.domain,
            "count": len(self.memories),
            "digest": self.digest,
        }


def _text(value: Any, label: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise AdmissionError(f"{label} must be nonempty text of at most {limit} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise AdmissionError(f"{label} contains control characters")
    return value


def _source(raw: Any, content: str) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != {
        "ref", "version", "sha256", "content_sha256", "observed_at", "evidence_type"
    }:
        raise AdmissionError("source requires exact provenance fields")
    ref = _text(raw["ref"], "source.ref")
    if not ref.startswith(_ALLOWED_SOURCE_PREFIXES):
        raise AdmissionError("source.ref needs an explicit namespace")
    if ref != ref.strip() or any(char in ref for char in "\r\n\t"):
        raise AdmissionError("source.ref must be a single canonical locator")
    version = _text(raw["version"], "source.version", 256)
    observed_at = _text(raw["observed_at"], "source.observed_at", 64)
    if not _UTC_TIMESTAMP.fullmatch(observed_at):
        raise AdmissionError("source.observed_at requires a full UTC timestamp")
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        raise AdmissionError("source.observed_at is not a valid calendar date") from None
    evidence_type = _text(raw["evidence_type"], "source.evidence_type", 96)
    expected_type = next(
        (kind for prefix, kind in _SOURCE_TYPES.items() if ref.startswith(prefix)),
        None,
    )
    if evidence_type != expected_type:
        raise AdmissionError("source.ref namespace and evidence_type mismatch")
    for label in ("sha256", "content_sha256"):
        if not isinstance(raw[label], str) or not _SHA256.fullmatch(raw[label]):
            raise AdmissionError(f"source.{label} requires lowercase SHA-256")
    actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if raw["content_sha256"] != actual_hash:
        raise AdmissionError("source.content_sha256 does not match projected content")
    # The full source hash is caller-supplied, NOT verified by this adapter.
    return dict(raw)


def _normalise(raw: Any, bank: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {
        "schema", "record_id", "kind", "domain", "bank", "classification",
        "content", "source", "review_state"
    }:
        raise AdmissionError("record requires exact projection fields")
    if raw["schema"] != SCHEMA:
        raise AdmissionError("unsupported projection schema")
    rid = _text(raw["record_id"], "record_id", 128)
    if not _ID.fullmatch(rid):
        raise AdmissionError("invalid record_id")
    if not isinstance(raw["kind"], str) or raw["kind"] not in KINDS:
        raise AdmissionError("unsupported record kind")
    if raw["domain"] != DOMAIN or raw["bank"] != bank:
        raise AdmissionError("domain/bank mismatch")
    if raw["classification"] != "architecture_internal":
        raise AdmissionError("classification not admitted to shared architecture")
    if raw["review_state"] != "reviewed_candidate":
        raise AdmissionError("only explicitly reviewed candidates can be previewed")
    content = _text(raw["content"], "content", _MAX_CONTENT)
    source = _source(raw["source"], content)
    return {
        "content": content,
        "source": "owned-architecture-projection",
        "scope": "global",
        "metadata": {
            "projection_schema": SCHEMA,
            "record_id": rid,
            "kind": raw["kind"],
            "domain": DOMAIN,
            "bank": bank,
            "classification": raw["classification"],
            "source": source,
            "review_state": "reviewed_candidate",
            "authority": "DERIVED_CONTEXT_ONLY",
            "verified_source": False,
        },
    }


def plan_projection(records: Iterable[Any], *, bank: str = "architecture") -> ProjectionPlan:
    """Validate a bounded set of records and produce a deterministic, no-write plan.

    A source verification claim cannot be established by self-attested input.
    The separate owning ingress must verify each source before real import.
    """
    if not isinstance(bank, str) or not _ID.fullmatch(bank) or bank == "default":
        raise AdmissionError("an explicit, non-default isolated bank is required")
    memories: list[dict[str, Any]] = []
    ids: set[str] = set()
    for count, raw in enumerate(records, start=1):
        if count > _MAX_RECORDS:
            raise AdmissionError("record limit exceeded")
        item = _normalise(raw, bank)
        rid = item["metadata"]["record_id"]
        if rid in ids:
            raise AdmissionError("duplicate record_id")
        ids.add(rid)
        memories.append(item)
    if not memories:
        raise AdmissionError("empty projection")
    memories.sort(key=lambda item: item["metadata"]["record_id"])
    canonical = json.dumps(memories, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
    return ProjectionPlan(
        bank=bank, domain=DOMAIN,
        digest=hashlib.sha256(canonical).hexdigest(),
        memories=tuple(memories),
    )


def preview_jsonl(stream: Iterable[str], *, bank: str = "architecture") -> dict[str, Any]:
    """Parse bounded JSONL and return metadata-only receipt without touching a DB."""
    def records():
        for line_number, line in enumerate(stream, start=1):
            if len(line.encode("utf-8")) > _MAX_LINE:
                raise AdmissionError(f"line {line_number}: size limit exceeded")
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                raise AdmissionError(f"line {line_number}: invalid JSON") from None
    return plan_projection(records(), bank=bank).receipt()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview reviewed architecture memory records, without writes")
    parser.add_argument("--input", required=True, help="JSONL file; '-' for stdin")
    parser.add_argument("--bank", default="architecture", help="Non-default isolated memory bank")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            result = preview_jsonl(sys.stdin, bank=args.bank)
        else:
            path = Path(args.input)
            if not path.is_file() or path.stat().st_size > _MAX_RECORDS * _MAX_LINE:
                raise AdmissionError("input file missing or exceeds size limit")
            with path.open("r", encoding="utf-8") as stream:
                result = preview_jsonl(stream, bank=args.bank)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (AdmissionError, UnicodeError, OSError) as exc:
        # Do not expose potentially sensitive text or source payload in errors.
        print(f"projection rejected: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

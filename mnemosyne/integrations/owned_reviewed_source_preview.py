"""Pure reviewed-source plan. Provider authentication is caller-owned, NOT supplied here.

Neither creating dataclass instances nor passing mocked readers grants owner
authority. No reads from real providers, writes, sync or model execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import re
from typing import Callable

from mnemosyne.integrations.owned_architecture_bridge import AdmissionError, KINDS, plan_projection

_VERSION_LIB = re.compile(r"^v[1-9][0-9]{0,9}$")
_VERSION_OBS = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
MAX_SOURCE_SNAPSHOT_AGE = timedelta(minutes=5)


@dataclass(frozen=True)
class Selection:
    record_id: str
    kind: str
    source_ref: str
    review_id: str
    excerpt: str


@dataclass(frozen=True)
class SourceRead:
    ref: str
    version: str
    raw: bytes
    observed_at: str


@dataclass(frozen=True)
class ReviewRead:
    review_id: str
    source_ref: str
    source_version: str
    source_sha256: str
    excerpt_sha256: str
    decision: str
    classification: str
    bank: str
    reviewer: str
    reviewed_at: str


def utc(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value
    ):
        raise AdmissionError("invalid timestamp format")
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise AdmissionError("invalid calendar date") from None
    if date > datetime.now(timezone.utc):
        raise AdmissionError("future attestation")
    return date


def source_kind(ref: str, version: str) -> str:
    if not isinstance(ref, str) or len(ref) > 512:
        raise AdmissionError("invalid source ref")
    if ref.startswith("library:/"):
        name = ref[len("library:/"):]
        valid = _VERSION_LIB
        kind = "canonical_document"
    elif ref.startswith("obsidian:"):
        name = ref[len("obsidian:"):]
        valid = _VERSION_OBS
        kind = "reviewed_note"
    else:
        raise AdmissionError("source namespace not admitted")
    if (not name or name.startswith("/") or "\\" in name
        or any(x in {"", ".", ".."} for x in name.split("/"))
        or any(ord(c) < 32 or ord(c) == 127 for c in name)
        or not isinstance(version, str) or not valid.fullmatch(version)):
        raise AdmissionError("noncanonical source path/version")
    return kind


def preview(selections: list[Selection], *, source_reader: Callable,
            review_reader: Callable) -> dict:
    """Return no-content receipt; never accepts approval from candidate input.

    The separately owned caller MUST bind both readers to independent current
    authenticated sources and attested review registers. This helper cannot do it.
    """
    if not isinstance(selections, list) or not 1 <= len(selections) <= 8:
        raise AdmissionError("selection bound")
    if not callable(source_reader) or not callable(review_reader):
        raise AdmissionError("independent owner readers required")
    records = []
    ids = set()
    review_ids = set()
    for item in selections:
        if not isinstance(item, Selection):
            raise AdmissionError("invalid selection")
        if (not isinstance(item.record_id, str) or not _ID.fullmatch(item.record_id)
            or not isinstance(item.review_id, str) or not _ID.fullmatch(item.review_id)
            or item.record_id in ids or item.review_id in review_ids
            or not isinstance(item.excerpt, str) or not 1 <= len(item.excerpt) <= 1200
            or not isinstance(item.kind, str) or item.kind not in KINDS
            or not isinstance(item.source_ref, str)):
            raise AdmissionError("invalid selection identity/content")
        # Validate the untrusted locator before touching either bound provider.
        source_kind(item.source_ref, "v1" if item.source_ref.startswith("library:/")
                    else "sha256:" + "0" * 64)
        try:
            source = source_reader(item.source_ref)
            review = review_reader(item.review_id)
        except Exception:
            # Provider exceptions can include private source contents/credentials.
            raise AdmissionError("owner source/review reader unavailable") from None
        if not isinstance(source, SourceRead) or not isinstance(review, ReviewRead):
            raise AdmissionError("owner source/review read unavailable")
        if source.ref != item.source_ref:
            raise AdmissionError("source identity mismatch")
        kind = source_kind(source.ref, source.version)
        if not isinstance(source.raw, bytes) or not 1 <= len(source.raw) <= 65536:
            raise AdmissionError("source size bound")
        try:
            contents = source.raw.decode("utf-8")
        except UnicodeError:
            raise AdmissionError("source requires UTF-8") from None
        if item.excerpt not in contents:
            raise AdmissionError("excerpt not verbatim")
        full_hash = hashlib.sha256(source.raw).hexdigest()
        if kind == "reviewed_note" and source.version != "sha256:" + full_hash:
            raise AdmissionError("Obsidian immutable version differs from note bytes")
        excerpt_hash = hashlib.sha256(item.excerpt.encode("utf-8")).hexdigest()
        observed = utc(source.observed_at)
        if datetime.now(timezone.utc) - observed > MAX_SOURCE_SNAPSHOT_AGE:
            raise AdmissionError("source snapshot no longer current")
        reviewed = utc(review.reviewed_at)
        if (review.review_id != item.review_id
            or review.source_ref != source.ref
            or review.source_version != source.version
            or not isinstance(review.source_sha256, str)
            or not _SHA.fullmatch(review.source_sha256)
            or review.source_sha256 != full_hash
            or review.excerpt_sha256 != excerpt_hash
            or review.decision != "APPROVED"
            or review.classification != "architecture_internal"
            or review.bank != "architecture"
            or not isinstance(review.reviewer, str)
            or not _ID.fullmatch(review.reviewer)
            or reviewed > observed):
            raise AdmissionError("independent review/source mismatch")
        records.append({
          "schema": "owned-architecture-memory-v1",
          "record_id": item.record_id, "kind": item.kind,
          "domain": "shared-architecture", "bank": "architecture",
          "classification": "architecture_internal",
          "review_state": "reviewed_candidate", "content": item.excerpt,
          "source": {"ref": source.ref, "version": source.version,
            "sha256": full_hash, "content_sha256": excerpt_hash,
            "observed_at": source.observed_at, "evidence_type": kind},
        })
        ids.add(item.record_id)
        review_ids.add(item.review_id)
    receipt = plan_projection(records, bank="architecture").receipt()
    receipt["source_admission"] = "PREVIEW_ONLY_UNBOUND_CALLER"
    receipt["review_count"] = len(review_ids)
    return receipt

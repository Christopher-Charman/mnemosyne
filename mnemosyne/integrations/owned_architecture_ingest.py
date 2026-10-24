"""Opt-in, source-bound ingestion into a non-default Mnemosyne bank.

Only pinned Git blobs from explicitly configured local checkouts are supported.
A matching string/hash in a user-supplied record is NOT a source attestation.
The verified memory and its ingestion receipt share one SQLite transaction.
Neither Obsidian, archive, Library, network sync nor external embeddings are used.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from mnemosyne.core.beam import _BeamConnection, _deferred_commits
from mnemosyne.integrations.owned_architecture_bridge import (
    AdmissionError, ProjectionPlan, plan_projection,
)

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_PATH = re.compile(r"^[A-Za-z0-9._/-]{1,512}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MAX_BLOB_BYTES = 2 * 1024 * 1024


class PinnedGitVerifier:
    """Verify against a trusted local repository root and exact Git commit.

    The repo -> checkout mapping is furnished by the owning operator, not the
    candidate record; a caller must provision and refresh those checkouts.
    This is a pinned local-Git attestation, not a live GitHub/API approval.
    """

    def __init__(self, repositories: Mapping[str, Path], git_bin: str = "git"):
        if not repositories:
            raise AdmissionError("an explicit trusted repository allowlist is required")
        self._repos: dict[str, Path] = {}
        for repo, directory in repositories.items():
            if not isinstance(repo, str) or not _REPO.fullmatch(repo):
                raise AdmissionError("invalid trusted repository identifier")
            root = Path(directory).resolve(strict=True)
            if not root.is_dir():
                raise AdmissionError("trusted checkout is not a directory")
            self._repos[repo] = root
        self._git = git_bin

    def _command(self, root: Path, *argv: str) -> bytes:
        try:
            result = subprocess.run(
                [self._git, "-C", str(root), *argv],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=20, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise AdmissionError("trusted Git read unavailable") from None
        if result.returncode or len(result.stdout) > _MAX_BLOB_BYTES:
            raise AdmissionError("pinned Git source not readable within bounds")
        return result.stdout

    def verify(self, memory: dict[str, Any]) -> dict[str, str]:
        """Verify one excerpt and its full document digest from Git objects."""
        src = memory["metadata"]["source"]
        locator = src["ref"]
        matches = [
            (repo, locator[len("git:" + repo + "/"):])
            for repo in self._repos if locator.startswith("git:" + repo + "/")
        ]
        if len(matches) != 1:
            raise AdmissionError("source is not in the trusted Git allowlist")
        repo, relative = matches[0]
        parts = relative.split("/")
        if (
            not _PATH.fullmatch(relative)
            or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or "\\" in relative
        ):
            raise AdmissionError("invalid exact Git source path")
        revision = src["version"]
        if not _COMMIT.fullmatch(revision):
            raise AdmissionError("source version must be an immutable 40-character Git commit")
        root = self._repos[repo]
        found_root = self._command(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
        if Path(found_root).resolve() != root:
            raise AdmissionError("trusted Git checkout root mismatch")
        origin = self._command(root, "remote", "get-url", "origin").decode("utf-8").strip()
        expected_origins = {
            f"https://github.com/{repo}", f"https://github.com/{repo}.git",
            f"git@github.com:{repo}", f"git@github.com:{repo}.git",
            f"ssh://git@github.com/{repo}", f"ssh://git@github.com/{repo}.git",
        }
        if origin not in expected_origins:
            raise AdmissionError("trusted Git checkout origin mismatch")
        if self._command(root, "cat-file", "-t", revision).strip() != b"commit":
            raise AdmissionError("source version is not a Git commit")
        tree = self._command(root, "ls-tree", revision, "--", relative).decode("utf-8")
        if len(tree.splitlines()) != 1:
            raise AdmissionError("source path is not one tracked Git blob")
        info, separator, stored_path = tree.partition("\t")
        if not separator or stored_path.strip() != relative:
            raise AdmissionError("Git tree path mismatch")
        attrs = info.split()
        if len(attrs) != 3 or attrs[0] not in {"100644", "100755"} or attrs[1] != "blob":
            raise AdmissionError("non-regular Git source objects are not admitted")
        data = self._command(root, "show", f"{revision}:{relative}")
        if hashlib.sha256(data).hexdigest() != src["sha256"]:
            raise AdmissionError("Git source full-file SHA-256 mismatch")
        if memory["content"].encode("utf-8") not in data:
            raise AdmissionError("memory content is not a verbatim source excerpt")
        return {
            "ref": locator,
            "commit": revision,
            "sha256": hashlib.sha256(data).hexdigest(),
            "method": "PINNED_LOCAL_GIT_BLOB",
        }


def _memory_fingerprint(memory: dict[str, Any]) -> str:
    encoded = json.dumps(memory, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def ingest_verified_records(
    records: list[dict[str, Any]],
    *,
    mnemosyne: Any = None,
    verifier: PinnedGitVerifier | None = None,
    bank: str = "architecture",
    enabled: bool = False,
) -> dict[str, Any]:
    """Plan by default; optionally atomically apply independently verified excerpts.

    This Python API has no CLI --apply option. To enable ingestion the caller
    must provide both a bound bank instance and a trusted-source verifier.
    Duplicate record IDs with different content or provenance fail closed.
    """
    plan: ProjectionPlan = plan_projection(records, bank=bank)
    if not enabled:
        return plan.receipt()
    if verifier is None or not isinstance(verifier, PinnedGitVerifier):
        raise AdmissionError("enabled import requires a pinned Git verifier")
    if mnemosyne is None or getattr(mnemosyne, "bank", None) != bank:
        raise AdmissionError("target Mnemosyne bank does not match the plan")
    path = Path(mnemosyne.db_path).resolve(strict=True)
    if path.name != "mnemosyne.db" or path.parent.name != bank or path.parent.parent.name != "banks":
        raise AdmissionError("only explicit isolated bank SQLite paths are admitted")
    conn = mnemosyne.conn
    if not isinstance(conn, _BeamConnection) or conn.in_transaction:
        raise AdmissionError("ingest requires an idle transaction-capable BEAM connection")

    # Verify ALL records against owner-bound immutable Git objects before
    # opening the transaction. An unverified source cannot partially import.
    verified = [(memory, verifier.verify(memory)) for memory in plan.memories]
    imported = 0
    replayed = 0
    with _deferred_commits(conn, immediate=True):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS owned_architecture_ingest_receipts ("
            "bank TEXT NOT NULL, record_id TEXT NOT NULL, fingerprint TEXT NOT NULL, "
            "memory_id TEXT NOT NULL, verification_method TEXT NOT NULL, "
            "PRIMARY KEY(bank,record_id))"
        )
        for memory, proof in verified:
            identifier = memory["metadata"]["record_id"]
            fingerprint = _memory_fingerprint(memory)
            existing = conn.execute(
                "SELECT fingerprint,memory_id FROM owned_architecture_ingest_receipts "
                "WHERE bank=? AND record_id=?", (bank, identifier)
            ).fetchone()
            if existing is not None:
                if existing[0] != fingerprint:
                    raise AdmissionError("record replay conflicts with committed provenance")
                stored = conn.execute(
                    "SELECT content,source,scope,metadata_json FROM working_memory WHERE id=?",
                    (existing[1],),
                ).fetchone()
                if stored is None:
                    raise AdmissionError("committed memory missing; explicit reconciliation required")
                try:
                    saved = json.loads(stored[3])
                except (TypeError, ValueError):
                    raise AdmissionError("committed memory metadata unreadable") from None
                expected = dict(memory["metadata"])
                expected.update(verified_source=True, verification_method=proof["method"])
                if (stored[0] != memory["content"] or stored[1] != memory["source"]
                    or stored[2] != memory["scope"] or not isinstance(saved, dict)
                    or any(saved.get(k) != v for k, v in expected.items())):
                    raise AdmissionError("committed memory drift; explicit reconciliation required")
                replayed += 1
                continue

            metadata = dict(memory["metadata"])
            metadata["verified_source"] = True
            metadata["verification_method"] = proof["method"]
            memory_id = mnemosyne.remember(
                memory["content"],
                source=memory["source"],
                scope=memory["scope"],
                metadata=metadata,
                trust_tier="IMPORTED",
                dedupe=False,
                extract=False,
                extract_entities=False,
            )
            if not memory_id:
                raise AdmissionError("Mnemosyne write policy rejected a candidate")
            if conn.execute(
                "SELECT 1 FROM working_memory WHERE id=?", (memory_id,)
            ).fetchone() is None:
                raise AdmissionError("memory effect not confirmed within transaction")
            conn.execute(
                "INSERT INTO owned_architecture_ingest_receipts "
                "(bank,record_id,fingerprint,memory_id,verification_method) "
                "VALUES(?,?,?,?,?)",
                (bank, identifier, fingerprint, memory_id, proof["method"]),
            )
            imported += 1
    return {
        "schema": "owned-architecture-ingest-receipt-v1",
        "status": "COMMITTED",
        "domain": plan.domain,
        "bank": bank,
        "plan_digest": plan.digest,
        "imported": imported,
        "replayed": replayed,
        "verified": len(verified),
        "verification_method": "PINNED_LOCAL_GIT_BLOB",
        "sync_enabled": False,
    }

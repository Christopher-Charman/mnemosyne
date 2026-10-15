"""Synthetic on-host regressions for pinned Git evidence and atomic ingest."""
import hashlib
import os
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest

from mnemosyne.core.memory import Mnemosyne
from mnemosyne.integrations.owned_architecture_ingest import (
    PinnedGitVerifier, ingest_verified_records,
)
from mnemosyne.integrations.owned_architecture_bridge import AdmissionError


def git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return p.stdout.decode().strip()


class OwnedIngestTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(prefix="mnemo-owned-test-")
        self.addCleanup(self.t.cleanup)
        self.root = pathlib.Path(self.t.name)
        self.repo = self.root / "repository"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "remote", "add", "origin",
            "https://github.com/Christopher-Charman/test-evidence.git")
        self.content = "Synthetic accepted memory excerpt. No private archive data."
        self.data = ("Heading.\n" + self.content + "\nTrailing text.\n").encode()
        (self.repo / "evidence.md").write_bytes(self.data)
        git(self.repo, "add", "evidence.md")
        git(self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.test",
            "commit", "-qm", "Synthetic provenance")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        self.verifier = PinnedGitVerifier({
            "Christopher-Charman/test-evidence": self.repo
        })
        self.bankroot = self.root / "data" / "banks" / "architecture"
        self.bankroot.mkdir(parents=True)
        self.memory = Mnemosyne(
            bank="architecture",
            db_path=self.bankroot / "mnemosyne.db",
            session_id="owned-ingest-test",
        )

    def record(self, rid="fixture.1", content=None):
        content = self.content if content is None else content
        return {
            "schema": "owned-architecture-memory-v1",
            "record_id": rid,
            "kind": "test",
            "domain": "shared-architecture",
            "bank": "architecture",
            "classification": "architecture_internal",
            "review_state": "reviewed_candidate",
            "content": content,
            "source": {
                "ref": "git:Christopher-Charman/test-evidence/evidence.md",
                "version": self.commit,
                "sha256": hashlib.sha256(self.data).hexdigest(),
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "observed_at": "2026-10-14T12:00:00Z",
                "evidence_type": "git_blob",
            },
        }

    def rows(self, table):
        return self.memory.conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def apply(self, records):
        return ingest_verified_records(
            records, mnemosyne=self.memory, verifier=self.verifier,
            enabled=True, bank="architecture",
        )

    def test_default_is_no_write(self):
        result = ingest_verified_records([self.record()])
        self.assertEqual(result["writes"], 0)
        self.assertEqual(self.rows("working_memory"), 0)
        with self.assertRaises(sqlite3.OperationalError):
            self.rows("owned_architecture_ingest_receipts")

    def test_applied_and_replayed_once(self):
        result = self.apply([self.record()])
        self.assertEqual((result["imported"], result["replayed"]), (1, 0))
        self.assertEqual(self.rows("working_memory"), 1)
        replay = self.apply([self.record()])
        self.assertEqual((replay["imported"], replay["replayed"]), (0, 1))
        self.assertEqual(self.rows("working_memory"), 1)
        self.assertEqual(self.rows("owned_architecture_ingest_receipts"), 1)

    def test_restart_replays(self):
        self.apply([self.record()])
        self.memory = Mnemosyne(
            bank="architecture", db_path=self.bankroot / "mnemosyne.db",
            session_id="owned-ingest-test",
        )
        self.assertEqual(self.apply([self.record()])["replayed"], 1)

    def test_record_id_conflict_rejected(self):
        self.apply([self.record()])
        other = self.record()
        other["kind"] = "correction"
        with self.assertRaises(AdmissionError):
            self.apply([other])
        self.assertEqual(self.rows("working_memory"), 1)

    def test_missing_memory_requires_reconciliation(self):
        self.apply([self.record()])
        stored = self.memory.conn.execute(
            "SELECT memory_id FROM owned_architecture_ingest_receipts"
        ).fetchone()[0]
        self.memory.forget(stored)
        with self.assertRaises(AdmissionError):
            self.apply([self.record()])

    def test_two_records_with_same_content_keep_separate_ids(self):
        result = self.apply([self.record("r1"), self.record("r2")])
        self.assertEqual(result["imported"], 2)
        self.assertEqual(self.rows("working_memory"), 2)

    def test_source_digest_tampering_rejected(self):
        x = self.record()
        x["source"]["sha256"] = "0" * 64
        with self.assertRaises(AdmissionError):
            self.apply([x])
        self.assertEqual(self.rows("working_memory"), 0)

    def test_non_verbatim_inference_rejected(self):
        x = self.record(content="This conclusion is not in source.")
        with self.assertRaises(AdmissionError):
            self.apply([x])
        self.assertEqual(self.rows("working_memory"), 0)

    def test_unpinned_source_rejected(self):
        x = self.record()
        x["source"]["version"] = "main"
        with self.assertRaises(AdmissionError):
            self.apply([x])

    def test_library_source_not_in_git_allowlist(self):
        x = self.record()
        x["source"]["ref"] = "library:/Architecture Control Plane/test.md"
        x["source"]["evidence_type"] = "canonical_document"
        with self.assertRaises(AdmissionError):
            self.apply([x])

    def test_unknown_repo_rejected(self):
        x = self.record()
        x["source"]["ref"] = "git:Other/Unknown/evidence.md"
        with self.assertRaises(AdmissionError):
            self.apply([x])

    def test_git_source_path_traversal_rejected(self):
        x = self.record()
        x["source"]["ref"] = "git:Christopher-Charman/test-evidence/../secrets"
        with self.assertRaises(AdmissionError):
            self.apply([x])

    def test_git_source_symlink_rejected(self):
        os.symlink("evidence.md", self.repo / "linked.md")
        git(self.repo, "add", "linked.md")
        git(self.repo, "-c", "user.name=Test", "-c", "user.email=test@example.test",
            "commit", "-qm", "Test symlink")
        x = self.record()
        x["source"]["version"] = git(self.repo, "rev-parse", "HEAD")
        x["source"]["ref"] = "git:Christopher-Charman/test-evidence/linked.md"
        with self.assertRaises(AdmissionError):
            self.apply([x])

    def test_wrong_git_origin_rejected(self):
        git(self.repo, "remote", "set-url", "origin", "https://github.com/Other/Owner.git")
        with self.assertRaises(AdmissionError):
            self.apply([self.record()])

    def test_no_partial_ingestion_if_second_record_unverified(self):
        good = self.record("r1")
        bad = self.record("r2", content="Not in pinned source")
        with self.assertRaises(AdmissionError):
            self.apply([good, bad])
        self.assertEqual(self.rows("working_memory"), 0)

    def test_receipt_insert_failure_rolls_back_memory(self):
        self.memory.conn.execute(
            "CREATE TABLE owned_architecture_ingest_receipts ("
            "bank TEXT NOT NULL, record_id TEXT NOT NULL, fingerprint TEXT NOT NULL, "
            "memory_id TEXT NOT NULL, verification_method TEXT NOT NULL, "
            "PRIMARY KEY(bank, record_id))"
        )
        self.memory.conn.execute(
            "CREATE TRIGGER reject_ingest BEFORE INSERT ON owned_architecture_ingest_receipts "
            "BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END"
        )
        self.memory.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.apply([self.record()])
        self.assertEqual(self.rows("working_memory"), 0)
        self.assertEqual(self.rows("memories"), 0)
        self.assertEqual(self.rows("owned_architecture_ingest_receipts"), 0)

    def test_derived_metadata_cannot_be_authority(self):
        self.apply([self.record()])
        row = self.memory.conn.execute(
            "SELECT metadata_json FROM memories LIMIT 1"
        ).fetchone()
        import json
        metadata = json.loads(row[0])
        self.assertEqual(metadata["authority"], "DERIVED_CONTEXT_ONLY")
        self.assertEqual(metadata["verification_method"], "PINNED_LOCAL_GIT_BLOB")
        self.assertEqual(metadata["review_state"], "reviewed_candidate")

    def test_wrong_bank_instance_rejected(self):
        self.memory.bank = "evenio"
        with self.assertRaises(AdmissionError):
            self.apply([self.record()])


if __name__ == "__main__":
    unittest.main()

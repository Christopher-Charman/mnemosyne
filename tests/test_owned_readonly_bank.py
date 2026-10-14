import hashlib
import json
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from mnemosyne.integrations.owned_readonly_bank import (
    ImmutableRecallError, recall_owner_bank,
)

class TestImmutableBankRecall(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="mnemo-immutable-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.dir=pathlib.Path(self.tmp.name)
        self.db=self.dir/"owner.db"
        c=sqlite3.connect(self.db)
        c.executescript("""
        CREATE TABLE working_memory(
          id TEXT PRIMARY KEY,content TEXT,source TEXT,scope TEXT,metadata_json TEXT,
          superseded_by TEXT,valid_until TEXT,importance REAL);
        CREATE TABLE owned_architecture_ingest_receipts(
          bank TEXT,record_id TEXT,fingerprint TEXT,memory_id TEXT,
          verification_method TEXT, PRIMARY KEY(bank,record_id));
        """)
        c.commit();c.close()
        self.env={
           "MNEMOSYNE_OWNER_BANK_DB":str(self.db),
           "MNEMOSYNE_OWNER_UID":str(os.getuid()),
        }
    def add(self, rid="r1", text="Synthetic architecture continuity approved content",
            verified=True, receipt=True):
        meta={
            "authority":"DERIVED_CONTEXT_ONLY","verified_source":verified,
            "record_id":rid, "verification_method":"PINNED_LOCAL_GIT_BLOB",
            "bank":"architecture", "domain":"shared-architecture",
            "review_state":"reviewed_candidate",
            "classification":"architecture_internal",
            "source":{"ref":"git:Example/Owned/source.md","version":"a"*40,
                      "sha256":"b"*64,
                      "content_sha256":hashlib.sha256(text.encode()).hexdigest()},
        }
        prior_meta=dict(meta)
        prior_meta["verified_source"]=False
        prior_meta.pop("verification_method",None)
        original={"content":text,"source":"owned-architecture-projection",
                  "scope":"global","metadata":prior_meta}
        fingerprint=hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False,
                   separators=(",",":")).encode("utf-8")).hexdigest()
        c=sqlite3.connect(self.db)
        c.execute("INSERT INTO working_memory VALUES (?,?,?,?,?,?,?,?)", (
            rid,text,"owned-architecture-projection","global",json.dumps(meta),None,None,0.8))
        if receipt:
            c.execute("INSERT INTO owned_architecture_ingest_receipts VALUES (?,?,?,?,?)",
             ("architecture",rid,fingerprint,rid,"PINNED_LOCAL_GIT_BLOB"))
        c.commit();c.close()
    def snapshot(self):
        return {
            f.name:hashlib.sha256(f.read_bytes()).hexdigest()
            for f in self.dir.iterdir() if f.is_file()
        }
    def recall(self,query="architecture continuity"):
        with patch.dict(os.environ,self.env):
            return recall_owner_bank(query,5)
    def test_empty_bank_never_writes(self):
        before=self.snapshot()
        self.assertEqual(self.recall(),[])
        self.assertEqual(self.snapshot(),before)
    def test_successful_hit_does_not_touch_sqlite_or_sidecars(self):
        self.add()
        before=self.snapshot()
        self.assertEqual(len(self.recall()),1)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(len(self.recall()),1)
        self.assertEqual(self.snapshot(),before)
    def test_no_matching_term_remains_readonly(self):
        self.add()
        before=self.snapshot()
        self.assertEqual(self.recall("unrelated-penguins"),[])
        self.assertEqual(self.snapshot(),before)
    def test_spoofed_metadata_without_receipt_never_returns(self):
        self.add(receipt=False)
        before=self.snapshot()
        self.assertEqual(self.recall(),[])
        self.assertEqual(self.snapshot(),before)
    def test_unverified_review_metadata_not_accepted(self):
        self.add(verified=False)
        self.assertEqual(self.recall(),[])
    def test_nonzero_wal_rejected_before_open(self):
        self.add()
        (self.dir/"owner.db-wal").write_bytes(b"not_a_checkpoint")
        before=self.snapshot()
        with self.assertRaises(ImmutableRecallError):
            self.recall()
        self.assertEqual(self.snapshot(),before)
    def test_changed_memory_content_does_not_pass_receipt(self):
        self.add()
        conn=sqlite3.connect(self.db)
        conn.execute("UPDATE working_memory SET content=? WHERE id=?",
                     ("Synthetic architecture continuity modified", "r1"))
        conn.commit();conn.close()
        before=self.snapshot()
        self.assertEqual(self.recall(),[])
        self.assertEqual(self.snapshot(),before)
    def test_changed_kind_does_not_pass_receipt(self):
        self.add()
        conn=sqlite3.connect(self.db)
        meta=json.loads(conn.execute("SELECT metadata_json FROM working_memory").fetchone()[0])
        meta["kind"]="correction"
        conn.execute("UPDATE working_memory SET metadata_json=? WHERE id=?", (json.dumps(meta),"r1"))
        conn.commit();conn.close()
        self.assertEqual(self.recall(),[])
    def test_changed_ingest_receipt_rejected(self):
        self.add()
        conn=sqlite3.connect(self.db)
        conn.execute("UPDATE owned_architecture_ingest_receipts SET fingerprint=? WHERE record_id=?",("0"*64,"r1"))
        conn.commit();conn.close()
        self.assertEqual(self.recall(),[])
    def test_content_digest_mismatch_rejected(self):
        self.add()
        conn=sqlite3.connect(self.db)
        meta=json.loads(conn.execute("SELECT metadata_json FROM working_memory").fetchone()[0])
        meta["source"]["content_sha256"]="f"*64
        conn.execute("UPDATE working_memory SET metadata_json=? WHERE id=?", (json.dumps(meta),"r1"))
        conn.commit();conn.close()
        self.assertEqual(self.recall(),[])
    def test_missing_owner_config_fails_closed(self):
        with patch.dict(os.environ,{"MNEMOSYNE_OWNER_BANK_DB":"",
                                  "MNEMOSYNE_OWNER_UID":""}):
            with self.assertRaises(ImmutableRecallError):
                recall_owner_bank("continuity",3)
    def test_wrong_uid_fails_closed(self):
        self.env["MNEMOSYNE_OWNER_UID"]=str(os.getuid()+1)
        with self.assertRaises(ImmutableRecallError):
            self.recall()
    def test_schema_missing_receipt_table_rejected(self):
        c=sqlite3.connect(self.db)
        c.execute("DROP TABLE owned_architecture_ingest_receipts")
        c.commit();c.close()
        before=self.snapshot()
        with self.assertRaises(ImmutableRecallError):
            self.recall()
        self.assertEqual(self.snapshot(),before)

if __name__=="__main__":
    unittest.main()

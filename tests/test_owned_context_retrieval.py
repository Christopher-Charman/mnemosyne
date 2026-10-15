"""No-write, synthetic tests for historical and derived context federation."""
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from mnemosyne.integrations.owned_context_retrieval import (
    ContextBoundaryError, build_context, invoke_owned_reader,
)

def request():
    return {"schema":"owned-mnemosyne-context-request-v1",
            "request_id":"context-test-20261014-001","query":"continuity topology",
            "since":"2026-08-01","until":"2026-10-14","limit":2}

def packet():
    return {"schema":"owned-session-context-v1","state":"HISTORICAL_EVIDENCE_ONLY",
            "archive_index_generated_at":"2026-10-08T00:00:00Z",
            "history_gap_after_index":True,
            "records":[{"role":"user","message_id":"m1","conversation_id":"c1",
                         "text":"Synthetic continuity topology evidence","sha256":"a"*64,
                         "evidence_refs":["archive:fixture"],"text_truncated":False},
                       {"role":"assistant","message_id":"m2","conversation_id":"c1",
                         "text":"Synthetic assistant unverified claim","sha256":"b"*64,
                         "evidence_refs":[],"text_truncated":False}]}

class StubMemory:
    bank="architecture"
    def __init__(self,rows=()):self.rows=list(rows)
    def recall(self,query,top_k):return self.rows[:top_k]

class TestFederation(unittest.TestCase):
    def test_no_authority_escalation(self):
        r=build_context(request(),memory=StubMemory(),historical_packet=packet())
        self.assertEqual(r["state"],"READ_ONLY_CONTEXT")
        self.assertEqual(len(r["historical"]),2)
        self.assertFalse(r["automatic_agent_injection"])
        self.assertFalse(r["current_project_authority_verified"])
        self.assertEqual(r["mnemosyne"],[])
        self.assertFalse(r["memory_ingestion"])
    def test_assistant_not_authoritative(self):
        r=build_context(request(),memory=StubMemory(),historical_packet=packet())
        self.assertEqual(r["historical"][1]["role"],"assistant")
        self.assertFalse(r["historical"][1]["authorship_verified"])
    def test_verified_derived_projection_included(self):
        meta={"authority":"DERIVED_CONTEXT_ONLY","verified_source":True,
              "verification_method":"PINNED_LOCAL_GIT_BLOB","domain":"shared-architecture",
              "bank":"architecture","record_id":"rid",
              "source":{"ref":"git:Owner/Repo/doc.md","version":"c"*40}}
        row={"source":"owned-architecture-projection","content":"approved test","metadata":meta}
        r=build_context(request(),memory=StubMemory([row]),historical_packet=packet())
        self.assertEqual(r["mnemosyne"][0]["authority"],"DERIVED_CONTEXT_ONLY")
    def test_unverified_projection_omitted(self):
        row={"source":"owned-architecture-projection","content":"unsupported claim",
             "metadata":{"verified_source":False}}
        r=build_context(request(),memory=StubMemory([row]),historical_packet=packet())
        self.assertEqual(r["mnemosyne"],[])
    def test_cross_bank(self):
        m=StubMemory();m.bank="evenio"
        with self.assertRaises(ContextBoundaryError):
            build_context(request(),memory=m,historical_packet=packet())
    def test_oversize_date_window(self):
        q=request();q["since"]="2025-01-01"
        with self.assertRaises(ContextBoundaryError):
            build_context(q,memory=StubMemory(),historical_packet=packet())
    def test_extra_field(self):
        q=request();q["untrusted_control"]="shell"
        with self.assertRaises(ContextBoundaryError):
            build_context(q,memory=StubMemory(),historical_packet=packet())
    def test_missing_message_id(self):
        p=packet();del p["records"][0]["message_id"]
        with self.assertRaises(ContextBoundaryError):
            build_context(request(),memory=StubMemory(),historical_packet=p)
    def test_wrong_historical_role(self):
        p=packet();p["records"][1]["role"]="system"
        with self.assertRaises(ContextBoundaryError):
            build_context(request(),memory=StubMemory(),historical_packet=p)
    def test_excerpt_truncation(self):
        p=packet();p["records"][0]["text"]="z"*10000
        r=build_context(request(),memory=StubMemory(),historical_packet=p)
        self.assertEqual(len(r["historical"][0]["text"]),1800)
        self.assertTrue(r["historical"][0]["text_truncated"])
    def test_wrong_metadata_bank_omitted(self):
        row={"source":"owned-architecture-projection","content":"wrong bank",
             "metadata":{"verified_source":True,"verification_method":"PINNED_LOCAL_GIT_BLOB",
                         "authority":"DERIVED_CONTEXT_ONLY","domain":"shared-architecture","bank":"evenio"}}
        r=build_context(request(),memory=StubMemory([row]),historical_packet=packet())
        self.assertEqual(r["mnemosyne"],[])
    def test_reject_unverified_reader_packet(self):
        import types
        receipt={"request_id":"context-test-20261014-001","return_code":0,
                 "state":"EXECUTED_READ_ONLY",
                 "output":{"schema":"owned-session-context-v1","state":"HISTORICAL_EVIDENCE_ONLY",
                           "records":[],"automatic_session_injection":True,
                           "instructions_from_archive_authoritative":False,
                           "current_library_verified":False,"live_destination_verified":False}}
        mock=types.SimpleNamespace(returncode=0,stdout=json.dumps(receipt))
        with patch("mnemosyne.integrations.owned_context_retrieval.subprocess.run",return_value=mock), \
             patch.object(Path,"is_file",return_value=True), \
             patch.object(Path,"is_symlink",return_value=False), \
             patch("mnemosyne.integrations.owned_context_retrieval.os.access",return_value=True):
            with self.assertRaises(ContextBoundaryError):
                invoke_owned_reader("context-test-20261014-001","continuity topology","2026-08-01","2026-10-14",2)

if __name__=="__main__":
    unittest.main()

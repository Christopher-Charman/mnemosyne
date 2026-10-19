"""Synthetic, no-provider-I/O preview tests."""
import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from mnemosyne.integrations.owned_reviewed_source_preview import (
    Selection, SourceRead, ReviewRead, preview,
)
from mnemosyne.integrations.owned_architecture_bridge import AdmissionError

def stamp(delta=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta)).replace(
        microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")

class ReviewedSourcePreviewTests(unittest.TestCase):
    def setUp(self):
        self.line="Approved synthetic architecture note"
        self.raw=("# Fixture\n"+self.line+"\n").encode()
        self.i=Selection("review.record.001", "decision",
            "library:/Architecture/Synthetic.md", "review.ticket.001", self.line)
        self.s=SourceRead(self.i.source_ref, "v3", self.raw,stamp())
        self.r=ReviewRead(self.i.review_id,self.s.ref,self.s.version,
            hashlib.sha256(self.raw).hexdigest(),
            hashlib.sha256(self.line.encode()).hexdigest(),
            "APPROVED", "architecture_internal", "architecture",
            "reviewer.synthetic.001", stamp(-60))
    def plan(self, item=None, source=None, review=None):
        i=self.i if item is None else item
        s=self.s if source is None else source
        r=self.r if review is None else review
        return preview([i], source_reader=lambda x:s, review_reader=lambda x:r)
    def test_library_preview_receipt_is_metadata_only(self):
        result=self.plan()
        self.assertEqual(result["writes"],0)
        self.assertEqual(result["count"],1)
        self.assertEqual(result["source_admission"],"PREVIEW_ONLY_UNBOUND_CALLER")
        self.assertNotIn(self.line,str(result))
    def test_library_paths_with_internal_spaces(self):
        ref="library:/Architecture Control Plane/Synthetic Decision.md"
        item=replace(self.i,source_ref=ref)
        source=replace(self.s,ref=ref)
        review=replace(self.r,source_ref=ref)
        self.assertEqual(self.plan(item,source,review)["count"],1)

    def test_nonstring_source_ref_rejected_before_provider_io(self):
        calls=[]
        for ref in (None,5,[],{}):
            with self.subTest(ref=ref), self.assertRaises(AdmissionError):
                preview([replace(self.i,source_ref=ref)],
                    source_reader=lambda x:calls.append("source"),
                    review_reader=lambda x:calls.append("review"))
        self.assertEqual(calls,[])

    def test_obsidian_digest_preview(self):
        ref="obsidian:Memory/Synthetic.md"
        ver="sha256:"+hashlib.sha256(self.raw).hexdigest()
        i=replace(self.i, source_ref=ref)
        s=replace(self.s, ref=ref, version=ver)
        r=replace(self.r, source_ref=ref,source_version=ver)
        self.assertEqual(self.plan(i,s,r)["count"],1)
    def test_forged_obsidian_version_denied(self):
        ref="obsidian:Memory/Synthetic.md"
        wrong="sha256:"+"0"*64
        item=replace(self.i,source_ref=ref)
        source=replace(self.s,ref=ref,version=wrong)
        review=replace(self.r,source_ref=ref,source_version=wrong)
        with self.assertRaises(AdmissionError):
            self.plan(item,source,review)
    def test_source_byte_drift_denied(self):
        with self.assertRaises(AdmissionError):
            self.plan(source=replace(self.s,raw=self.raw+b"changed"))
    def test_unreviewed_denied(self):
        for status in ("PENDING","REVOKED","SELF_ATTESTED"):
            with self.subTest(status=status), self.assertRaises(AdmissionError):
                self.plan(review=replace(self.r,decision=status))
    def test_review_binding_denied(self):
        for field,value in [("source_version","v2"),("bank","evenio"),
                            ("review_id","wrong.review.001"),
                            ("classification","personal_private"),
                            ("reviewer",""),("excerpt_sha256","0"*64),
            ("source_sha256","0"*64),
            ("source_ref","library:/Architecture/Other.md")]:
            with self.subTest(field=field),self.assertRaises(AdmissionError):
                self.plan(review=replace(self.r,**{field:value}))
    def test_no_forged_excerpt(self):
        with self.assertRaises(AdmissionError):
            self.plan(item=replace(self.i,excerpt="not in source"))
    def test_version_and_traversal_denied(self):
        for ref in ("library:/A/../B","obsidian:../secret","archive:test"):
            with self.subTest(ref=ref),self.assertRaises(AdmissionError):
                self.plan(item=replace(self.i,source_ref=ref),
                    source=replace(self.s,ref=ref),review=replace(self.r,source_ref=ref))
        with self.assertRaises(AdmissionError):
            self.plan(source=replace(self.s,version="latest"))
    def test_stale_source_snapshot_denied_even_when_review_matches(self):
        old=stamp(-3600)
        source=replace(self.s, observed_at=old)
        review=replace(self.r, reviewed_at=stamp(-7200))
        with self.assertRaisesRegex(AdmissionError, "no longer current"):
            self.plan(source=source, review=review)

    def test_invalid_selection_fails_before_provider_call(self):
        calls=[]
        for change in ({"kind":"not-a-kind"}, {"source_ref":"archive:secret"}):
            with self.subTest(change=change), self.assertRaises(AdmissionError):
                preview([replace(self.i,**change)],
                    source_reader=lambda x: calls.append("source"),
                    review_reader=lambda x: calls.append("review"))
        self.assertEqual(calls,[])

    def test_provider_exception_is_redacted(self):
        def failing_reader(ref):
            raise RuntimeError("PRIVATE_SECRET_IN_PROVIDER_ERROR")
        with self.assertRaises(AdmissionError) as raised:
            preview([self.i], source_reader=failing_reader,
                    review_reader=lambda ref:self.r)
        self.assertNotIn("PRIVATE_SECRET_IN_PROVIDER_ERROR",str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_future_and_stale_review_denied(self):
        with self.assertRaises(AdmissionError):
            self.plan(source=replace(self.s,observed_at=stamp(-120)))
        with self.assertRaises(AdmissionError):
            self.plan(review=replace(self.r,reviewed_at=stamp(3600)))
    def test_batch_and_duplicate_denied(self):
        with self.assertRaises(AdmissionError):
            preview([],source_reader=lambda r:self.s,review_reader=lambda r:self.r)
        with self.assertRaises(AdmissionError):
            preview([self.i]*2,source_reader=lambda r:self.s,
                    review_reader=lambda r:self.r)
    def test_invalid_provider_results_denied(self):
        with self.assertRaises(AdmissionError):
            preview([self.i],source_reader=lambda r:{"source":"self"},
                    review_reader=lambda r:self.r)
        with self.assertRaises(AdmissionError):
            preview([self.i],source_reader=lambda r:self.s,
                    review_reader=lambda r:{"status":"APPROVED"})
if __name__=="__main__":
    unittest.main()

"""Offline admission regressions; no Mnemosyne DB, network, or credentials used."""

import hashlib
import json
import unittest

from mnemosyne.integrations.owned_architecture_bridge import (
    AdmissionError, plan_projection, preview_jsonl,
)


def fixture(rid="decision.1", content="Use canonical evidence for decisions."):
    return {
        "schema": "owned-architecture-memory-v1",
        "record_id": rid,
        "kind": "decision",
        "domain": "shared-architecture",
        "bank": "architecture",
        "classification": "architecture_internal",
        "content": content,
        "review_state": "reviewed_candidate",
        "source": {
            "ref": "library:/Architecture Control Plane/DECISION.md",
            "version": "8",
            "sha256": "a" * 64,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "observed_at": "2026-10-14T04:00:00Z",
            "evidence_type": "canonical_document",
        },
    }


class ProjectionTests(unittest.TestCase):
    def test_deterministic_plan_independent_of_order(self):
        a, b = fixture("one"), fixture("two", "Second conclusion")
        first = plan_projection([a, b])
        second = plan_projection([b, a])
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(len(first.memories), 2)
        self.assertTrue(all(m["metadata"]["authority"] == "DERIVED_CONTEXT_ONLY"
                            for m in first.memories))

    def test_receipt_redacts_content_and_source(self):
        secret = "synthetic private test fixture ABC"
        result = preview_jsonl([json.dumps(fixture(content=secret))])
        serialized = json.dumps(result)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("DECISION.md", serialized)
        self.assertEqual(result["writes"], 0)
        self.assertFalse(result["sync_enabled"])
        self.assertEqual(result["mode"], "READ_ONLY_PREVIEW")

    def test_input_is_unmodified(self):
        original = fixture()
        before = json.dumps(original, sort_keys=True)
        plan_projection([original])
        self.assertEqual(json.dumps(original, sort_keys=True), before)

    def test_reject_empty(self):
        with self.assertRaises(AdmissionError):
            plan_projection([])

    def test_reject_duplicate(self):
        with self.assertRaises(AdmissionError):
            plan_projection([fixture(), fixture()])

    def test_reject_default_bank(self):
        with self.assertRaises(AdmissionError):
            plan_projection([fixture()], bank="default")

    def test_reject_cross_bank(self):
        with self.assertRaises(AdmissionError):
            plan_projection([fixture()], bank="evenio")

    def test_reject_non_architecture_domain(self):
        a = fixture()
        a["domain"] = "evenio"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_non_string_kind(self):
        a = fixture()
        a["kind"] = ["decision"]
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_sensitive_classification(self):
        a = fixture()
        a["classification"] = "personal"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_unreviewed(self):
        a = fixture()
        a["review_state"] = "unknown"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_hash_mismatch(self):
        a = fixture()
        a["content"] = "Changed excerpt"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_missing_provenance_field(self):
        a = fixture()
        del a["source"]["version"]
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_unscoped_source_locator(self):
        a = fixture()
        a["source"]["ref"] = "/tmp/unknown.md"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_source_namespace_type_confusion(self):
        a = fixture()
        a["source"]["evidence_type"] = "runtime_receipt"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_malformed_source_timestamp(self):
        a = fixture()
        a["source"]["observed_at"] = "2026-99-99T35:00:00Z"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_source_locator_newline(self):
        a = fixture()
        a["source"]["ref"] += "\nInjected-Header: yes"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_accept_precise_utc_timestamp(self):
        a = fixture()
        a["source"]["observed_at"] = "2026-10-14T04:00:00.123Z"
        self.assertEqual(len(plan_projection([a]).memories), 1)

    def test_reject_unexpected_authority_field(self):
        a = fixture()
        a["authority"] = "override"
        with self.assertRaises(AdmissionError):
            plan_projection([a])

    def test_reject_overlong_line(self):
        with self.assertRaises(AdmissionError):
            preview_jsonl(["x" * 40000])

    def test_reject_invalid_json(self):
        with self.assertRaises(AdmissionError):
            preview_jsonl(["{not json"])

    def test_reject_more_than_256(self):
        with self.assertRaises(AdmissionError):
            plan_projection(fixture(str(i)) for i in range(257))

    def test_reject_control_character(self):
        a = fixture(content="allowed")
        a["source"]["ref"] = "git:bad\u0000path"
        with self.assertRaises(AdmissionError):
            plan_projection([a])


if __name__ == "__main__":
    unittest.main()

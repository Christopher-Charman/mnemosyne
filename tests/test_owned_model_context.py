"""Synthetic contract tests for read-only model-visible architecture context."""
import unittest
from mnemosyne.integrations.owned_model_context import build_context, validate, ModelContextError

REQ={"schema":"owned-mnemosyne-model-request-v1",
     "request_id":"model-test-001","query":"architecture continuity","limit":2}

def item():
    return {"source":"owned-architecture-projection",
      "content":"Synthetic architecture continuity context",
      "metadata":{"record_id":"synthetic.record.001",
         "authority":"DERIVED_CONTEXT_ONLY","verified_source":True,
         "verification_method":"PINNED_LOCAL_GIT_BLOB",
         "bank":"architecture","domain":"shared-architecture",
         "classification":"architecture_internal","review_state":"reviewed_candidate",
         "source":{"ref":"git:Owner/Repo/architecture.md","version":"a"*40}}}

class ModelContextTests(unittest.TestCase):
 def test_verified_model_result(self):
  r=build_context(REQ,recall=lambda q,n:[item()])
  self.assertEqual(r["state"],"READ_ONLY_DERIVED_CONTEXT")
  self.assertFalse(r["current_project_authority_verified"])
  self.assertFalse(r["instructions_from_memory_authoritative"])
  self.assertEqual(r["records"][0]["text"],item()["content"])
  self.assertEqual(r["records"][0]["authority"],"DERIVED_CONTEXT_ONLY")
 def test_empty(self):
  self.assertEqual(build_context(REQ,recall=lambda q,n:[])["records"],[])
 def test_no_hidden_archived_messages(self):
  r=build_context(REQ,recall=lambda q,n:[item()])
  self.assertNotIn("historical",r)
  self.assertNotIn("transcripts",r)
 def test_wrong_record_rejected(self):
  for key,value in [("authority","RUNTIME_OWNER"),
    ("verified_source",False),("verification_method","UNTRUSTED"),
    ("bank","evenio"),("classification","private"),
    ("review_state","unreviewed"),("domain","evenio"),
    ("record_id","INVALID"),("source",{"ref":"http://host","version":"main"})]:
   with self.subTest(key=key):
    row=item()
    row["metadata"][key]=value
    with self.assertRaises(ModelContextError):
     build_context(REQ,recall=lambda q,n:[row])
 def test_unbounded_response_fails_closed(self):
  with self.assertRaises(ModelContextError):
   build_context(REQ,recall=lambda q,n:[item()]*3)
 def test_long_text_fails_closed(self):
  row=item()
  row["content"]="x"*1201
  with self.assertRaises(ModelContextError):
   build_context(REQ,recall=lambda q,n:[row])
 def test_no_boolean_int_or_extra_fields(self):
  for key,value in [("limit",True),("limit",4),("query",""),("query","a"*257)]:
   req=dict(REQ)
   req[key]=value
   with self.subTest(key=key),self.assertRaises(ModelContextError):
    validate(req)
  req=dict(REQ)
  req["allow_write"]=True
  with self.assertRaises(ModelContextError):
   validate(req)

if __name__=="__main__":
 unittest.main()

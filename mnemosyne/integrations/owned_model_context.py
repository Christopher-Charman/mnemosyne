"""Owner-only, read-only verified Mnemosyne context for model presentation.

No historical transcripts, sync, DB writes, remote calls, or runtime owner
decisions. Reviewed derived text is untrusted evidence, never instructions.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Callable

from mnemosyne.integrations.owned_readonly_bank import recall_owner_bank

SCHEMA = "owned-mnemosyne-model-request-v1"
RESULT_SCHEMA = "owned-mnemosyne-model-context-v1"
RID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
REV = re.compile(r"^[a-f0-9]{40}$")
MAX_INPUT = 2048
MAX_RESULT = 12000
MAX_TEXT = 1200

class ModelContextError(ValueError):
    pass

def validate(request: Any) -> tuple[str, str, int]:
    if not isinstance(request, dict) or set(request) != {"schema","request_id","query","limit"}:
        raise ModelContextError("invalid request schema")
    if request.get("schema") != SCHEMA:
        raise ModelContextError("invalid schema version")
    rid, query, limit = request["request_id"],request["query"],request["limit"]
    if not isinstance(rid,str) or not RID.fullmatch(rid):
        raise ModelContextError("invalid request identity")
    if not isinstance(query,str) or not 1 <= len(query) <= 256 or any(ord(ch)<32 for ch in query):
        raise ModelContextError("invalid query")
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ModelContextError("invalid result limit")
    return rid,query,limit

def build_context(request: Any, *, recall: Callable | None = None) -> dict[str, Any]:
    rid,query,limit=validate(request)
    find=recall if recall is not None else recall_owner_bank
    rows=find(query,limit)
    if not isinstance(rows,list) or len(rows)>limit:
        raise ModelContextError("unbounded recall")
    records=[]
    for row in rows:
        if not isinstance(row,dict) or row.get("source") != "owned-architecture-projection":
            raise ModelContextError("unexpected memory source")
        meta=row.get("metadata")
        if not isinstance(meta,dict):
            raise ModelContextError("missing metadata")
        src=meta.get("source")
        content=row.get("content")
        if (meta.get("authority")!="DERIVED_CONTEXT_ONLY"
            or meta.get("verified_source") is not True
            or meta.get("verification_method")!="PINNED_LOCAL_GIT_BLOB"
            or meta.get("classification")!="architecture_internal"
            or meta.get("review_state")!="reviewed_candidate"
            or meta.get("bank")!="architecture"
            or meta.get("domain")!="shared-architecture"
            or not isinstance(meta.get("record_id"),str)
            or not RID.fullmatch(meta["record_id"])
            or not isinstance(src,dict)
            or not isinstance(src.get("ref"),str)
            or not src["ref"].startswith("git:")
            or not isinstance(src.get("version"),str)
            or not REV.fullmatch(src["version"])
            or not isinstance(content,str)
            or not 1 <= len(content) <= MAX_TEXT
            or any(ord(ch)<32 and ch not in "\n\t" for ch in content)):
            raise ModelContextError("unverified model memory record")
        records.append({
           "record_id":meta["record_id"],"text":content,
           "source_ref":src["ref"],"source_version":src["version"],
           "authority":"DERIVED_CONTEXT_ONLY",
        })
    return {
       "schema":RESULT_SCHEMA,"request_id":rid,"state":"READ_ONLY_DERIVED_CONTEXT",
       "authority":"DERIVED_CONTEXT_ONLY","domain":"shared-architecture",
       "bank":"architecture","records":records,
       "current_project_authority_verified":False,
       "instructions_from_memory_authoritative":False,
       "ingestion_enabled":False,"sync_enabled":False
    }

def main() -> int:
    try:
        if os.environ.get("MNEMOSYNE_OWNER_UID","") == "" or os.getuid()!=int(os.environ["MNEMOSYNE_OWNER_UID"]):
            raise ModelContextError("owner identity mismatch")
        raw=sys.stdin.buffer.read(MAX_INPUT+1)
        if len(raw)>MAX_INPUT:
            raise ModelContextError("request exceeds bound")
        response=build_context(json.loads(raw.decode("utf-8")))
        encoded=json.dumps(response,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        if len(encoded.encode("utf-8"))>MAX_RESULT:
            raise ModelContextError("response exceeds bound")
    except (ModelContextError,ValueError,TypeError,OSError,UnicodeError):
        print(json.dumps({"schema":RESULT_SCHEMA,"state":"BLOCKED","reason":"ADMISSION_FAILED"}))
        return 2
    print(encoded)
    return 0

if __name__=="__main__":
    raise SystemExit(main())

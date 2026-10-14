# Owned shared-architecture → Mnemosyne (preview v1)

**Status: candidate adapter, not a deployed ingestion or sync service.**

The user-owned continuity archive and Obsidian knowledge graph retain their
owning provenance and authority. This adapter prepares **derived, untrusted
memory context** for future review before independent import into an isolated
Mnemosyne bank. It does not connect to the archive, Obsidian, GitHub, remote
embedding providers, Mnemosyne databases or the network.

## Preview

```sh
python -m mnemosyne.integrations.owned_architecture_bridge --input approved-candidates.jsonl --bank architecture
```

Pass JSON Lines with each record using this exact shape:

```json
{
  "schema": "owned-architecture-memory-v1",
  "record_id": "decision.1",
  "kind": "decision",
  "domain": "shared-architecture",
  "bank": "architecture",
  "classification": "architecture_internal",
  "review_state": "reviewed_candidate",
  "content": "Use canonical evidence for decisions.",
  "source": {
    "ref": "library:/Architecture Control Plane/DECISION.md",
    "version": "8",
    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "content_sha256": "SHA256_OF_CONTENT_UTF8",
    "observed_at": "2026-10-14T04:00:00Z",
    "evidence_type": "canonical_document"
  }
}
```

The sample `content_sha256` is a **placeholder**: replace it with the
actual lowercase SHA-256 of the UTF-8 `content` value. Supported record
kinds include facts, decisions, hypotheses, methods, tests, outcomes,
corrections, lessons, and task frontiers.

The command returns counts, plan SHA-256, explicit no-write/no-sync status and
the selected non-default bank. It never prints projected memory content.

## Admission boundary

- Input provenance and `review_state` are **caller assertions**. Matching
  a projected-content checksum **does not** authenticate the underlying
  document, review, live state or current authority.
- An owning ingress must independently verify source identity, exact source
  version/hash, retrieval scope, currentness, domain access, classification,
  approval and deduplication before any persistent memory write.
- No archive transcript, personal health data, secrets or Evenio business data
  should pass through a public repository, public CI workflow or shared bank.
- Mnemosyne memory remains a retrieval projection. Retrieved context is never
  sufficient authority to rewrite canonical documents, task state, runtime
  state or coordination leases.
- Synchronisation must be separately admitted after verifying endpoint
  authentication, client encryption, bank-level isolation, delta conflicts,
  crash recovery and provenance retention. Do not rely on the upstream sync
  server to enforce per-bank replication until that behaviour is proven.
- This preview is deliberately **read-only**. No `--apply` path exists.

Offline tests:

```sh
python -m unittest discover -s tests -p 'test_owned_architecture_bridge.py' -v
```

Next increments: owning-source verification callback; persisted idempotent import
receipt with crash recovery; bank-scoped sync security review; OpenWebUI/Codex MCP
recall adapter and operational dashboard telemetry. Each requires separate tests.

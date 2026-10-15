# Opt-in pinned-source ingestion — phase 2

Source: mnemosyne/integrations/owned_architecture_ingest.py

The existing read-only JSONL preview remains the default. The separate
ingest_verified_records Python API requires enabled=True, a Mnemosyne instance
bound to a non-default architecture SQLite bank, and a PinnedGitVerifier with
an operator-supplied exact repository-to-checkout allowlist.

The verifier accepts only regular Git file blobs at immutable commit SHAs.
It checks the checkout's canonical origin, full file SHA-256, provenance
namespace and version, and verbatim inclusion of the candidate text in the
file. It cannot independently establish who reviewed the source, verify
Library/Obsidian/archive records, or prove the pinned commit is the latest.
Those owners must have separate adapters; never treat this as universal
canonical approval or native ChatGPT integration.

Successful writes and their unique bank+record_id receipts use the same
Mnemosyne BEAM SQLite transaction. Identical replays skip existing records;
record ID collisions with changed evidence, missing committed memories,
partial write errors and unsupported source schemes fail closed. No LLM
extraction, sync or external embedding is performed by this adapter.
Use the MNEMOSYNE_NO_EMBEDDINGS=1 environment setting when running tests or
staging locally until embedding policy is separately accepted.

No production ingest or deployment has been enabled. The test suite uses
synthetic Git repositories and temporary SQLite banks. Never commit raw
private memory or credentials to this public source repository.

Example of an explicitly approved local caller:

    verifier = PinnedGitVerifier({"OWNER/REPO": Path("/trusted/checkout")})
    result = ingest_verified_records(
        reviewed_records, verifier=verifier, mnemosyne=isolated_architecture_bank,
        bank="architecture", enabled=True,
    )

The caller MUST first establish destination/runtime authority, bank ownership,
allowlist trust, data classification, review evidence, and collision admission.
An exact pinned Git blob is still untrusted content and must never override
the current source of project, task, runtime or coordination truth.

Remaining gates: source-review attestation beyond the candidate's own flag;
authoritative Library/archive reader; explicit updates/supersession;
crash/replay concurrency across processes; encrypted bank-scoped device sync;
OpenWebUI/Codex/ChatGPT bridge; monitored deployment.

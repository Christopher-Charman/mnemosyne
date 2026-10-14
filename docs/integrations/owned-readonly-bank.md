# Strict owner-configured no-write recall boundary

A direct Mnemosyne/BeamMemory construction or recall is not a read-only
operation: initialisation can create/migrate tables and normal recall tracks
hits with SQLite UPDATE statements. The owned historical-context bridge must
never call those APIs.

The public adapter now uses an immutable, bounded SQLite accessor. Its
owner-specific settings are injected by an **owned runtime launcher**, not
published as paths, UIDs or private runtime labels in this public fork:

- MNEMOSYNE_OWNER_UID
- MNEMOSYNE_OWNER_RUNTIME_ID
- MNEMOSYNE_OWNER_CONTEXT_READER
- MNEMOSYNE_OWNER_BANK_DB

The bank must have been created and admitted by an independent owner writer,
with source-verified ingest receipts. There is no initialization or database
migration in the read path. An uncheckpointed nonzero SQLite WAL refuses
immutable reads to avoid silently stale derived context. No receipt table
or owner-configured path means fail closed (not an empty positive proof).
The historical reader must be a regular executable file. These environment
variables come only from the trusted host configuration, not a user request.

The isolation tests compare all fixture file bytes and names before/after
empty, successful-hit, miss, and denied reads; they also test missing
configuration, nonzero WAL and receipt provenance. In-memory/synthetic tests
do not establish historical review authority or current runtime truth.

Older public Git objects still contain host-specific labels from prior commits:
a new public Git revision cannot expunge those objects. Treat remediation of
previously published operational metadata as a distinct owner privacy task.

Reader integrity now also validates a stored source/content SHA-256 and reconstructs the original canonical projection fingerprint with verified_source reset to false, then matches it to the atomic ingest receipt. This detects accidental or one-sided tampering. It does not defend against an adversary who can replace both the memory row and receipt, or independently attest the public Git origin at query time.

Expiry uses SQLite chronological julianday(valid_until) > julianday('now'),
matching upstream Mnemosyne working-memory expiry semantics. Offset-bearing
aware UTC, SQLite naive UTC, ISO Z and malformed dates have synthetic
fail-closed read-only regression coverage. Malformed non-NULL values are excluded.

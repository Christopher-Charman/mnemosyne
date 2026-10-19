# Reviewed Library/Obsidian source preview (candidate, NOT activated)

This code produces a metadata-only read-only preview plan. The owner-scoped caller
must independently bind and authenticate both its current source reader and
its reviewer/approval record reader. The dataclasses are not authentication.
Untrusted selected input has no approval, trust, owner or digest fields.

The source and review reads must match exact stable identifiers, full bytes
and version, excerpt digest, reviewed classification and actor decision. Native
Library source refs use a version token vN, while Obsidian notes are bound to
a complete SHA-256 version. Such a token is not independent provider verification.

Use existing Open-Obsidian-Integration Canvas promotion for selected reviewed
nodes and source manifests. Never auto-promote PARSED/raw transcripts, private
personal or health data, secrets or unreviewed Assistant Lessons. The source
adapter reads no Library/Obsidian content itself and cannot verify live auth.

No live SQLite importer or alternate mutation transport is introduced. Current
Mnemosyne PinnedGitVerifier remains Git-only. Live owner ingestion, non-Git
model presentation, reviewed source adapters and cross-device sync remain OFF
until separate user-owned destination controls and canaries are accepted.

Obsidian SHA-256 version must exactly match independently read full note bytes.

## Obsidian vault source-reader candidate

The owner-bound read_vault_note function retrieves only one explicit Markdown
note from an owner-pinned vault. File-descriptor based path traversal, no-follow
flags, UID and mode checks, hardlink rejection, 64 KiB bound, stable before/
after fstat checks, UTF-8 validation and whole-file SHA-256 limit the read.
Tests use disposable synthetic vaults; no live vault content was accessed.
The caller must still independently authenticate current vault provenance and
a distinct review-register decision. Note front matter or Canvas promotion
alone does not establish that decision. No live ingestion or sync.

The preview rejects source snapshots older than five minutes; the caller must
re-read current source bytes and current review decision for every invocation.
Invalid selection kinds/locators are rejected before provider calls; provider
exception details are redacted. This freshness bound does not make a source
reader or review record independently authenticated.

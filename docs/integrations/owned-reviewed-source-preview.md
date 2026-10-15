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

# Owner Obsidian ↔ private GitHub review gate (read-only)

`mnemosyne.integrations.owned_obsidian_review_gate` connects the existing
owner-scoped POSIX vault note reader and metadata-only preview to a **fresh,
independently authenticated private GitHub issue-comment review**. It is **not
an ingest adapter**. It cannot create reviewed memory, import it into SQLite,
write to the vault, issue GitHub approvals, or enable sync/embeddings.

## Trust boundaries

- The operator explicitly pins the **private** GitHub review repository, exact
  issue number, numeric owner account ID, and each review ID → comment ID.
  A candidate note or selected excerpt supplies none of these permissions.
- The `gh api` caller must already possess the authorized private-repository
  credential. The adapter verifies the current repository owner, private
  visibility, comment/issue identity, numeric comment-author identity and
  GitHub `OWNER` author association. A synthetic injected API is valid **only
  for unit tests**, never proof of authenticated production operation.
- Review comments use strict JSON with the exact fields below. No Markdown
  fences, note contents, personal history, access token or private bank records
  are published to public source code or CI. The reviewer timestamp is sourced
  from GitHub's current `updated_at`, not candidate metadata.
- **All** selections are checked before any provider I/O. **All** private
  reviews must be authenticated and `APPROVED` **before** any vault bytes are
  opened. The source path must be under `Memory/Curated/` and end in `.md`.
  Symlinks, hardlinks, unowned/unsafe paths and changed note content are denied
  by the existing owner POSIX reader and exact source SHA-256 binding.
- Reviews and repository private ownership are read again **after** the vault
  check. A changed/revoked approval fails the preview. This is best-effort
  currentness, not an atomic transaction across GitHub and POSIX; no persistent
  write is performed or allowed by this module.
- Current architecture bank is always `architecture`, classification always
  `architecture_internal` and authority always `DERIVED_CONTEXT_ONLY`.
  ChatGPT raw exports, health/personal data, ordinary `Memory/Reference` notes,
  assistant lessons and unrelated project notes are not eligible here.

## Review comment body (in a private operator-owned GitHub issue)

```json
{
  "schema": "owned-mnemosyne-reviewed-obsidian-gh-comment-v1",
  "review_id": "review.example.001",
  "source_ref": "obsidian:Memory/Curated/Example.md",
  "source_version": "sha256:<actual full note SHA-256>",
  "source_sha256": "<actual full note SHA-256>",
  "excerpt_sha256": "<actual selected excerpt SHA-256>",
  "decision": "APPROVED",
  "classification": "architecture_internal",
  "bank": "architecture"
}
```

The placeholders are descriptive only, **not valid attestations**. Create
an approval only after separately checking the exact curated note and excerpt.
A source note's YAML frontmatter, Canvas `PROMOTED` tag, or a GitHub comment
from a different user does not grant reviewer authority.

## Invocation boundary

The owning runner explicitly constructs a `Selection`, then constructs
`GitHubIssueReviewReader` with a **verified operator-pinned** account ID,
private repo/issue and review/comment mapping, and invokes
`preview_reviewed_vault(selections, vault_root=Path(...), owner_uid=os.getuid(),
reviews=reader)`. The result is a **metadata-only** `READ_ONLY_PREVIEW`
receipt (`writes=0`, no contents, no sync). An actual reviewed note must exist
first; neither the importer nor this gate creates one implicitly.

Before permitting persistent non-Git ingestion, implement a distinct
provenance-retaining, transactionally idempotent bank importer with owner
admission/CAS, unchanged reader authority, a rollback path and live consuming
caller acceptance. The current `PinnedGitVerifier` supports Git-only imports;
using it to treat Obsidian hashes as pinned Git evidence would be incorrect.

## Verification

Run `python3.12 -S -m unittest discover -s tests -p 'test_owned_*.py' -q`
from a Miniconda-managed checkout. All tests use ephemeral synthetic vaults
and a fake provider. Separately, a live **read-only** `gh api` canary may check
private repository metadata and reject an existing unapproved operational
comment: rejecting a comment is not admission of a note. No hosted CI or paid
service is required for these local tests.

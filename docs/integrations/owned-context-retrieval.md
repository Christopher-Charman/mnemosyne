# Federated local read-only context

This integration reuses the existing bounded, owner-verified historical
context reader instead of querying or modifying the raw archive DB.

Installed caller (PowerPC runtime) supplies JSON via stdin:
{"schema":"owned-mnemosyne-context-request-v1",
"request_id":"owner-query-unique-20261014",
"query":"continuity topology",
"since":"2026-08-01","until":"2026-10-14","limit":2}

The returned historical and Mnemosyne arrays have distinct authority labels.
A historical statement or memory is never current project or runtime authority.
This first bridge is explicit-caller only; no OpenWebUI hook, public listener,
automatic ingestion, vector-model API or cross-device sync is enabled.

The historical archive reader still has a post-index coverage gap, so later
chats and current canonical sources require separate retrieval. Obsidian
authority and provenance must never be inferred from lexical matches alone.
Use no personally sensitive data in public code, CI fixtures or workflow logs.

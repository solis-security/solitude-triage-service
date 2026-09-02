# ADR 0004 — Evidence identity is a content hash; Elasticsearch is a projection

- Status: Proposed
- Date: 2026-09-02
- Related: TDD §4.2, §4.6, §5, §8 (Data integrity), §9; FR-06

## Context

This is the most expensive decision to defer, because evidence ids leak into
everything downstream: findings reference them, AI grounding validates against
them, the audit log records them, and reports cite them. Once ids appear in a
delivered report, changing the scheme is a migration across artefacts we do not
control.

TDD §4.2 requires that raw data land in an "immutable Raw Evidence Store
(append-only, hashed) before any transformation, preserving forensic integrity",
with normalised copies in a separate Case Data Store. §8 requires that normalised
copies never overwrite raw. §9 requires hashing to preserve chain of custody. §5
gives `Raw Evidence Item` a `hash` field.

Today there is one tier. `app/es_client.py` writes documents to Elasticsearch with
`_id = doc["id"]`, so re-ingesting a record with the same id **silently
overwrites** the stored evidence, leaving no trace that it changed. `evidence_id`
is an Elasticsearch `_id`. There is no hash anywhere, and no raw tier. For a tool
whose output is intended to be defensible in a legal context, that is a real
integrity gap rather than a missing nice-to-have.

## Decision

Two tiers, with a clear system of record:

- **Raw Evidence Store** — append-only object storage. Every ingested record is
  stored verbatim and hashed on arrival. This is the system of record.
- **Elasticsearch** — a normalised, queryable *projection* of the raw store.
  Disposable by design: it can be dropped and rebuilt from raw at any time.

**`evidence_id` becomes the content hash of the raw record, not an Elasticsearch
`_id`.** Identity is derived from content, so the same record ingested twice is
the same evidence, and a record that differs by one byte is a different evidence
item rather than a silent overwrite.

Ingestion becomes append-only: re-ingesting identical content is a no-op;
ingesting changed content under a previously seen id creates a new evidence item
and is surfaced, never merged.

## Consequences

- Chain of custody becomes demonstrable: a report cites a hash, and the hash can
  be recomputed from the raw store to prove the evidence behind a conclusion has
  not changed.
- The AI grounding check gains real force. Today it proves a model cited an id it
  was given; with content-addressed ids it proves the citation refers to specific
  immutable content.
- Rebuilding the ES projection stops being a data-loss event, which in turn makes
  mapping changes and reindexing safe operations.
- Cost: an object store dependency, a hashing step on ingest, and ingestion is no
  longer idempotent-by-overwrite — duplicate detection has to be explicit.
- Migration: existing demo/test cases carry ES `_id` values as evidence ids. Since
  nothing has shipped in a report, this is the cheapest it will ever be to change.

## Rejected alternatives

**Keep Elasticsearch as the system of record.** Simplest, and adequate for a
demo. But ES is mutable by design, a reindex or mapping change can alter or lose
documents, and `bulk_index` already overwrites on id collision. It cannot support
the §9 chain-of-custody claim, and the claim is the point.

**Add a `hash` field to ES documents without a raw tier.** A hash stored in the
same mutable place as the data it attests to proves nothing — anything able to
rewrite the document can rewrite the hash.

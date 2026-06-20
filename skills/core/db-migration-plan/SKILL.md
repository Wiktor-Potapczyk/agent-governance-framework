---
name: db-migration-plan
description: Use BEFORE applying a database schema change (PostgreSQL / Supabase): adding or dropping a column, changing a type, adding an index, splitting or renaming a table, backfilling data. Produces a dated, reviewable migration plan with an expand→migrate→contract sequence, an index strategy with the reasoning narrated, a backfill plan, an explicit rollback path, and a verification checklist. NOT for running the migration (that's manual / n8n / Supabase SQL) and NOT for diagnosing a migration that already broke (that's process-postmortem). Triggers: migration, schema change, add column, add index, alter table, backfill, zero-downtime, ALTER, DDL.
---

# Database Migration Plan

A migration plan is **the safe-ordering of an irreversible-by-default operation**. The schema is shared state; a careless `ALTER` locks a table, breaks live readers, or strands data with no way back. This skill turns "change the schema" into a sequenced, reversible, verifiable plan: *before* any DDL runs.

Routing: for anything requiring query plans, lock analysis, or index-type selection, dispatch **`postgres-pro`**: it owns EXPLAIN, lock modes, and index internals. This skill owns the *plan structure + safety sequencing*; postgres-pro owns the *Postgres specifics*.

**Database-indexing learning goal (the owner):** whenever this skill proposes an index, it MUST narrate the choice: which columns, which index type (btree / hash / GIN / BRIN / partial / composite), the column order and why, and the read-vs-write tradeoff. An index added without a stated reason is a plan defect.

## Use-when

- A schema change is planned and not yet applied (column/type/table/index/constraint change, or a data backfill)
- The change touches a table with live readers/writers (zero-downtime ordering matters)
- An n8n workflow or app depends on the current shape and must not break mid-migration

## Do-NOT-use-when

- The migration already ran and broke something → `process-postmortem` (root-cause the failure)
- It's a brand-new table no live code reads yet → just write the `CREATE TABLE`; no migration sequencing needed
- The task is query performance with no schema change → dispatch `postgres-pro` directly

## Gotchas

- **`ALTER TABLE` lock modes bite.** On Postgres, adding a column with a volatile/non-constant default, changing a type, or adding a non-`CONCURRENTLY` index takes an `ACCESS EXCLUSIVE` lock that blocks all reads+writes for the rewrite. Always state the lock each step takes.
- **`CREATE INDEX` must be `CONCURRENTLY`** on a live table (and it cannot run inside a transaction block). Plan it as its own step.
- **Drops are the irreversible step.** Never drop a column/table in the same migration that stops using it: expand→contract: deploy code that no longer needs it, verify, then drop in a *later* migration once rollback is no longer wanted.
- **Supabase specifics:** RLS policies and the PostgREST schema cache. A column rename/drop can break RLS policies and stale the PostgREST cache (`NOTIFY pgrst, 'reload schema'`). Check both. (Supabase keys also reject browser-shaped User-Agents: use a curl-style UA if hitting the REST API to verify.)
- **Backfill is not free.** A `UPDATE ... SET col = ...` over a large table is one long-lock transaction unless batched. Plan backfills in bounded batches.

## Steps

### 1: Capture current state (live, not assumed)

Read the *live* schema, not a cached migration file. For Supabase/Postgres, get the table DDL, existing indexes, constraints, RLS policies, and approximate row count. Record what live code (apps, n8n workflows) reads the affected columns: a migration that breaks a reader it didn't know about is the top failure mode.

Write a `MIGRATION SCOPE` block:

    MIGRATION SCOPE
    Table(s): [name(s)]
    Change: [what changes: one line]
    Live readers/writers: [apps, n8n workflows, RLS policies that touch this]
    Row count (approx): [N: drives batching/lock decisions]
    Reversibility: [is the end state droppable-back? where's the point of no return?]
    Output path: Projects/[Name]/work/YYYY-MM-DD-migration-[table].md

### 2: Sequence with expand → migrate → contract

Never do additive + destructive in one step. Produce an ordered step list; for EACH step state: the SQL, the **lock it takes**, whether it's reversible, and the rollback for that step.

1. **Expand**: add the new column/table/index, nullable/backward-compatible, no reader changes yet. (`ADD COLUMN ... NULL`; `CREATE INDEX CONCURRENTLY`.)
2. **Backfill**: populate new shape in bounded batches (state batch size + the key it pages on); idempotent and re-runnable.
3. **Migrate readers**: switch app/n8n code to the new shape; both old and new shapes valid at this point (the safety window).
4. **Verify**: confirm new path works in production before anything is dropped (see Step 4).
5. **Contract**: *in a later migration*, once rollback is no longer wanted: drop the old column/constraint/index. This is the irreversible step and is gated to a deliberate decision.

### 3: Index strategy (narrated: learning-goal requirement)

For every index the plan adds or relies on, state: columns + order, index type and why, partial/`WHERE` predicate if applicable, and the write-amplification cost. If query-plan evidence is needed, dispatch `postgres-pro` to produce EXPLAIN before/after. Do not propose an index "to be safe": propose it for a named query pattern.

### 4: Rollback + verification

- **Rollback path:** for each non-contract step, the exact reverse SQL. State the single point of no return (usually the contract drop) explicitly.
- **Verification checklist:** the queries/checks that prove the migration succeeded: row counts match, new column populated, the dependent n8n workflow executes green, RLS still enforces, PostgREST cache reloaded. This is the empirical gate before declaring done.

### 5: Quality check

- [ ] Every step states its lock + rollback
- [ ] No additive + destructive in the same step (expand≠contract)
- [ ] Backfill is batched + idempotent (if a backfill exists)
- [ ] Every index is narrated (columns, type, order, tradeoff)
- [ ] Rollback path complete; point-of-no-return named
- [ ] Verification checklist is executable, not aspirational
- [ ] Output saved to the `work/` path

## Notes

- This skill plans; it does not run DDL. Applying the migration stays a human/n8n/Supabase action: surface the plan, let the maintainer apply.
- The contract (drop) step is the irreversible boundary: treat it like the n8n destructive-promotion gate: surface it explicitly, never bundle it with the expand.
- A migration plan with no rollback is not a plan.

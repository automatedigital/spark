# Session event persistence

Spark stores active conversation state as ordered SQLite events plus
transactional message/session projections. `append_iteration()` commits one
assistant iteration, all tool results, usage deltas, and status in one WAL
transaction. Subscribers are invoked only after that transaction commits.

Each event has a session-local monotonic sequence and an idempotency key.
Clients and internal consumers resume with `after_sequence`; periodic settled
checkpoints record the projection version, shell state, last message ID, and
sequence. Existing message rows are backfilled lazily with restart-safe
`legacy-message:<id>` keys. Existing JSON exports remain readable and are never
deleted by migration.

Full session JSON is materialized only when a turn settles. During active tool
work, committed SQLite events are the crash-recovery authority, avoiding a
complete JSON rewrite after every intermediate message.

The rollback boundary is dual-read compatibility: old message/JSON records
remain intact, `get_messages()` stays authoritative for transcript reads, and
the event tables can be ignored by an older application version.

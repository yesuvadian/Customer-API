"""Shared locks for "read current max/count for a pattern, then insert"
sequence-number generation (request_number, procurement_number,
workflow_number, ...) - not atomic on its own, so two concurrent creates
targeting the same unique-constrained column can read the same current
value before either commits and compute the identical "next" one, which
the database then rejects with an IntegrityError (surfacing as a raw 500).

One lock per TARGET COLUMN, not per file: multiple service classes
generate request_number for the same TestingRequest table (creating a
normal request, an auto-created repair-lifecycle request, and a direct
submission all write to it), so they must all serialize against the SAME
lock to actually prevent collisions between them - a lock private to just
one of those files would not see the others.

WEB_CONCURRENCY=1 and sync route handlers run in a shared thread pool, so
every concurrent request in this deployment is a thread in the SAME
process - a threading.Lock is therefore sufficient here. It would NOT
protect against a second worker PROCESS or a second server instance also
writing these tables; that would need a database-level equivalent instead
(e.g. SELECT ... FOR UPDATE on a per-pattern counter row), since a Python
lock only ever spans one process's memory.
"""

import threading

TESTING_REQUEST_NUMBER_LOCK = threading.Lock()
PROCUREMENT_NUMBER_LOCK = threading.Lock()
REPAIR_WORKFLOW_NUMBER_LOCK = threading.Lock()

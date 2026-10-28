# S1 supplemental operational read repair — 2026-10-29

This supersedes the execution handoff in `evaluation-inventory-repair-2026-10-29.md`.
The active proof directory is
`artifacts/fresh-evaluation-measurement-repaired-2026-10-27/s1-read-repair-v9`.
Use its `go-review.json`, `transition-authorization.json`, and `sol-handoff.json`
for the exact source commit, profile, freeze and current execution owner.

## Preserved boundary

All original main29 attempts are closed: valid21 (recovered18, not recovered3),
invalid8. Do not rerun the three valid unrecovered outcomes. The first S1
supplement (`s1-b02-a-supplement01/attempt-01`) failed during measurement and
then failed its initial cleanup. Sol closed it under unchanged inventory-v8
source253: strict invalid, cleanup true, with a separate before-cleanup copy
and sealed invalid copy. Original 10234 files, the preceding invalid21 files,
and the two newly completed main results remained unchanged. Worker 1/auto,
same three existing GCP VM identities, clean fixtures, and original clock
configuration were verified. Closure evidence is in
`inventory-execution-2026-10-29/s1-supplement01-failure/closure.json`.

## Cause and repair

1. kubectl actually reported `The connection to the server 127.0.0.1:16444 was
   refused`. The transient classifier only matched `connection refused`, so
   the S1 reconnect callback was never invoked. Match the canonical sentence
   while retaining permanent-error precedence, identity checks, command caps,
   cumulative deadline and original H.
2. CPU capture used `/tmp` although the registered application explicitly has
   `readOnlyRootFilesystem: true`. The capture intent recorded `Errno 30`, and
   subsequent reads could not find the file. Capture once into the existing
   `/dev/shm` tmpfs instead. Preserve the same `/sys/fs/cgroup/cpu.stat` input,
   capture/readback protocol and original CPU interpretation. No image,
   Pod security context, workload, load, trigger, SLO or judgement changes.
3. The cleanup transport watcher repaired the missing tunnel only after the
   first cleanup command had already failed. After checking ownership, run
   the existing coordinated local tunnel ensure synchronously before cleanup.
   Do not replay cleanup mutations or measurement actions.

The new continuation gate compares these three mixed modules against the
frozen predecessor AST, allowing only the exact changes above. Other source
changes are the explicit supplement plan, release checks, registry hashes and
regression tests. The old clock, calibration, inventory and worker preparation
code remains byte-identical; its prior evidence retains its original source.

## Verification

- Full `test_fresh*.py` suite: 203 passed. A draft test expected one identity
  check, but the existing contract checks before retry and after readback;
  that assertion was corrected and the draft failure preserved separately.
- The actual registered image and security context were used in an owned,
  out-of-sample Job in `default`. CPU capture succeeded once in `/dev/shm`.
- The managed local tunnel was stopped. The actual S1 read adapter received
  the canonical refusal, restored the tunnel, and read the same Job's logs
  with stable UID in 19.366 seconds within its original 60-second budget.
  Only the adapter's in-process namespace was bound to the fixture namespace.
- The fixture was deleted with its UID precondition and absence verified.
  A second local tunnel stop exercised actual `LiveBackend.cleanup`; its
  synchronous preflight restored transport and all cleanup checks passed.
- Qualification source stayed unchanged. The initial operator-only YAML
  conversion parser failed before fixture creation; its directory/log and
  script were preserved, then the JSON stream parser was corrected. It was
  never an experiment attempt.

## Execution plan and ownership

New cohort: `bed-s1-read-v9`. No main or preparation measurements are repeated.
Execute in this order, one driver and one attempt at a time:

1. s2-b03-p-supplement01
2. s3-b02-m3600-supplement01
3. s3-b03-m3600-supplement01
4. s3-b03-p3600-supplement01
5. s4-b01-off-supplement01
6. s4-b02-on-supplement01
7. s4-b02-off-supplement01
8. s1-b02-a-supplement02

The original invalid S1 supplement01 remains a separate excluded result.
The new plan reserves supplement02 even though supplement01 is already
finished. All current-cohort completed work is excluded from subsequent
forward reservations only after its immutable evidence is checked.

Astra owns repair until explicit GO handoff. Sol chat
`01a18317-e6fb-7ef0-8e7e-bb80dd3c5fa5` then owns sequential execution.
Astra retains the existing 30-minute heartbeat; do not create a duplicate.
On a new operational failure, stop the next fault, preserve evidence, close
owned cleanup, review the cause, qualify a new source and create a separate
later supplement if warranted. Do not overwrite or promote invalid attempts.

The full remaining eight-case estimate plus lifecycle is approximately
26999 seconds. Recompute credit with the latest displayed balance, elapsed
time, remaining work, 40000 KRW cleanup reserve, 20000 KRW other reserve and
the explicitly unconfirmed 12-hour posting-lag assumption. The historical
ledger must not be subtracted again. Admission remains within credit only;
no paid conversion, cash overage or new GCP host VM is authorized.

After all supplements: complete separate primary/supplement/operational
analysis and report, owned cleanup, VM stop, ledger closure, and original
clock restoration. Then disable/delete Astra's heartbeat. Do not archive
the prior chats.

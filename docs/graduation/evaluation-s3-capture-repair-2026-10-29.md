# S3 process capture continuation, 2026-10-29

The v9 S2 supplement completed valid/recovered/safe/clean. The next
`s3-b02-m3600-supplement01` stopped at JSON decoding before injection acceptance;
its attempt remains invalid, sealed and cleanup=true. Main29 remain valid21 /
invalid8, including three valid unrecovered outcomes that must not be replayed.
There are three closed supplemental attempts: one valid and two invalid.

## Reproduced cause and change

On the actual surviving worker, `crictl ps --name db -o json` wrote valid JSON.
Successful `iptables -C` checks printed their matched rules to stdout before
`cat` printed that file. The original chained expression therefore failed at
JSON character zero. The original failed response was not saved, so the new
reproduction is evidence of the same failing code path, not a recovered copy of
that historical response.

`fresh_s3_capture.read_s3_capture` redirects only the two successful rule-check
stdout streams to `/dev/null`, preserves their exit statuses and stderr, and
checkpoints the raw capture response before JSON decoding. It never repeats
fault injection or recreates a bad capture. Fault commands, ownership checks,
container/Pod UID matching, H, SLO, load and judgement remain unchanged; an AST
comparison against frozen v9 enforces that scenario boundary.

210 tests passed. Live qualification uses the pinned database image in an owned
Pod and empty owned iptables chains, with no DROP rule, data volume or experiment
attempt. It reproduces the old parser failure, validates the exact production
reader against the same running container/Pod UID and confirms owned cleanup.
The first qualification's deletion wait expired after the fixed reader passed;
its actual resource absence was independently confirmed and its evidence was
preserved. A new fixture with one-second termination grace verifies the complete
qualification and cleanup. This setting belongs only to the temporary fixture.

## Separate continuation

New cohort: `bed-s3-capture-v10`. Execute these seven cases in this order:

1. s3-b03-m3600-supplement01
2. s3-b03-p3600-supplement01
3. s4-b01-off-supplement01
4. s4-b02-on-supplement01
5. s4-b02-off-supplement01
6. s1-b02-a-supplement02
7. s3-b02-m3600-supplement02

Preserve all original attempts and both invalid supplemental attempts. Preserve
valid S2 supplement01 and all valid unrecovered outcomes. The new authorization
is `user-authorized-s3-capture-continuation-v7`; its audit binds the full source,
profile, historical freezes, tests, actual qualification and forward budget.
Only the artifact cohort, latest credit reference and environment run ID change
in the profile. The same three host VM IDs and management cluster UIDs are
verified after the intervening safety stop/restart.

The user reported used314551 / total435523 KRW at receipt
2026-10-28T22:43:37Z, giving remaining120972 KRW. Billing cutoff is unknown.
Reserve all remaining work (about6.73h including final lifecycle25min),
subsequent elapsed usage, cleanup40000, other20000, and unconfirmed12h posting
lag32000. Recalculate at admission; never subtract old ledger totals again.
No cash overage, paid conversion or new GCP host VM is authorized.

## Evidence and ownership

Authoritative directory under
`artifacts/fresh-evaluation-measurement-repaired-2026-10-27/`:
`s3-process-read-investigation-v10/`, particularly `reproduction.json`,
`tests.json`, `qualification.json`, `admission-readback.json`,
`remaining-budget.json`, `transition-authorization.json`, `go-review.json` and
`sol-handoff.json`. Read these actual records for current status and commit.
Until GO and handoff, Astra holds sole source/infra ownership and HOLD remains.
After handoff, Sol owns sequential execution; Astra only monitors every30min.
Do not launch a duplicate driver or edit source during an active attempt.

# Bounded packaging repair after job 6434655

Historical record: these were the earlier setup attempts. The user subsequently
authorized realistic margins, [Step 1 passed](REPORT.md), and the
[controlled comparison completed](../controlled-comparison/REPORT.md). The
earlier stopping points below are superseded by the renewed session plan.

The first allocation failed after 14 seconds with zero model requests, before
model startup. The source inventory glob included eight macOS AppleDouble
`._*.py` metadata sidecars generated during tar upload. No expected source was
missing or changed. The source-lock rejection correctly prevented execution.

This is an upload/inventory defect, not a result about the controller.

## Specific repair

- Exclude hidden metadata from the source inventory.
- Generate the upload using Python `tarfile`, which does not synthesize macOS
  sidecars, instead of the native macOS tar defaults.
- Make login-node preflight compare the exact non-hidden source inventory as
  well as all expected hashes, matching the driver's check.
- Keep the failed job, original spec, source lock, package inventory, hardware
  record, Slurm log, and diagnosis. The original implementation is commit
  `ca41a58`; its source hashes are in that attempt's source lock.

## Limit and unchanged mechanics

One replacement allocation is allowed after login-node diagnosis/preflight.
The revised saved spec is `week4.step1.v2-packaging-repair`. Its ceiling is
29 minutes, with a 26-minute driver timeout, 24 model requests, and no automatic
retries. Combined with the first job's 14 seconds, total allocation remains
below the original 30-minute compute ceiling. A further failure stops GPU work
for this step and is handed over with its diagnosis.

The policy implementation, questions, arrival offsets, budget lengths,
thresholds, sampling, engine settings, and smoke acceptance criteria are
unchanged. The first attempt generated no samples, so there is no selection or
inference rerun to conceal.

## Replacement outcome and stopping point

Job 6434705 failed at startup after 245 allocated seconds, before any policy
phase or request. Process inspection at 2:28 showed the server waiting in
`cl_sync_io_wait` with six CPU seconds; vLLM model/engine initialization appeared
late in the server log. The four-minute startup guard was too short for this
startup. The historical harness allowed ten minutes.

The saved two-attempt plan is now closed, with 259 total GPU-seconds (4:19,
approximately 0.072 GPU-hours), zero generated requests, and no active jobs.
No third allocation was submitted. Checkpoint 1C remains unverified.

At that stopping point, the code/spec prepared a 600-second startup allowance and a 24-minute
allocation / 21-minute driver cap for a future bounded attempt. This is CPU-
checked preparation, not a successful GPU run. A future allocation needs its
own recorded attempt limit and must preserve both previous failures.

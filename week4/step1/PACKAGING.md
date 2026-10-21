# Packaging and provenance

This folder consolidates the admission implementation, real GPU gate, and completed controlled comparison into one reviewable commit. The original unpushed implementation commits were squashed; historical commit IDs in saved manifests identify the original session, not commits required to reproduce analysis. Executed source snapshots, matching hashes, inputs, and environment inventories remain in each successful run directory.

## What changed during consolidation

Original working paths `week4/admission-control/` and `week4/controlled-comparison/` now sit under `week4/step1/`. Bootstrap repository resolution, launcher paths, and helper repository resolution were adjusted for that nesting. Current source locks describe these packaged sources. The current gate descriptor explains the bootstrap-only path adjustment; the original gate descriptor is preserved inside comparison job 6440653. Policy, adapter, engine service, budgets, sampling, and saved plan are unchanged. Packaging received CPU/offline replay validation; no new GPU run is claimed.

The final record checker no longer requires a duplicate provisional block snapshot: it checks the complete final data. The provisional/final agreement was checked before packaging. Reports, scores, cases, and figures retain the complete comparison. Original source paths inside run snapshots and manifests deliberately remain unchanged.

## Essential evidence retained

Both successful runs retain complete request/event records, inputs, frozen trace/configuration, executed source snapshots, package/hardware inventories, accounting, and validation. Comparison grades and review queue include all failures. Scheduler logs are stored as lossless gzip with raw/compressed SHA-256 and byte counts in `storage-manifest.json`; use `controlled-comparison/checks/pack_events.py --root RUN --unpack`. Plain logs and dependency caches are ignored by Git.

Repeated preflight/installation stdout and the duplicate partial block-0 collection are omitted. Successful final records supersede those progress copies. Two failed setup attempts remain visible with their diagnosis, configuration, validation, accounting, and complete archived-file SHA-256 indexes. They generated no requests and consumed 14 and 245 GPU seconds. The first was a macOS archive metadata issue, the second an unrealistically short startup guard. Neither was a failed scientific comparison.

## Privacy cleanup

Personal cluster logins, private workspace names, and local machine paths have been removed from the distributed documentation, launchers, manifests, and captured logs across the week folders. Launchers use local environment variables where a runtime location is needed. Analysis provenance uses repository-relative paths.

Sanitized source snapshots and their checksum references describe the files distributed here; they are no longer byte-for-byte copies of the original private execution files. Numeric outcomes, request timing, sampling, grades, and experimental conclusions are unchanged. The failed-attempt indexes retain original file hashes for context, but private retrieval locations are omitted. All records needed to audit the successful gate and comparison are included in Git.

Earlier commits may still contain the original private details; this cleanup updates the current repository contents and does not rewrite shared history.

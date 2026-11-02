# Arrival-only ablation and two matched development blocks

Originally approved for submission; both allocations were cancelled before execution on November 2, 2026, ahead of maintenance. Zero follow-up responses were produced. This preserves the frozen proposal and does not authorize a restart.

The design compares arrival-only decisions with live intervention using repeated matched traces. This scope is160measured responses+8engineering probes:two sequential H100allocations,each84requests and6hcap. Block2depends on successful completion ofBlock1;use afterok plus invalid-dependency cancellation. No retry,unfavorable-outcome replacement,additional parameter sweep,or background monitor.

## Question and interpretation

Does changing a running request add useful deadline-goodput or efficiency benefit beyond choosing a short budget only when a request arrives under pressure? Compare fixed4K,fixed8K,arrival-only,andlive. Arrival-only uses the identical existing arrival_budget function;it never changes an admitted request. Live combines that admission rule with existing in-flight reductions. Scientific controller/server,hardware class,budgets,cue,answer allowance,pressure threshold1,grading,arrival offsets,deadline236.32225114s,andT157.54816743sremain unchanged.

Focus on the existing near8request andburst/recovery12request conditions. Low is not repeated because the earlier four-request cohort had no successful answers and no queue;this is an explicitly exploratory follow-up design decision,not independent confirmation. The same12AIME2025development questions recur;there is no fresh-task claim.

## Matched repetitions

Block0seedbase6222;Block1seedbase16222;request seed=base+questionID. Same IDs and exact arrival/deadline recipes across all four policies within each block. Fresh server/engine per allocation;one engine across its phases,draining before every policy change.

Block0near order:fixed4K,fixed8K,arrival,live;burst:arrival,live,fixed4K,fixed8K. Block1reverses each order. This pairs early/late positions across two blocks,but is not complete four-position counterbalancing. The two blocks confound seed and run timing;they test repeatability under both changes,not separate variance components. Two blocks cannot establish robust population uncertainty or significance.

All trace files are generated before submission from the frozen Stage2calibration template. Outcomes and references do not enter trace construction. Deadlines/load scales are not retuned after results.

## Engineering gate and budgets

Each blockfirst runs the same4real-queue/recovery probes with that block's request seedbase. Require a real waiter,causal in-flight cuts with exact cue/state accounting,and a subsequent8Krecovery admission. Preserve capped outputs;correctness is not a gate criterion.900saggregate probe guard. Gate failure/inconclusive or injection failure stops its block before measurement;the dependent block must not run ifBlock0fails.

Then run80measured requests:8near+12burst ×4policies. Probe responses are separate. Same per-phase injection1slimit,1200srequest/drain guards,600sstartup aggregate guard,and340mininner bound. Per-block loose phase envelope:fournear last-offset441.135s+fourburst last-offset1220.998s+8×1200s=16248.53s(4h30m49s). Allow15minprobes,10minstartup,approximately5minpreflight:about5h01m,within340mininner/6houter caps. Expected2–3hours each after allocation,not a guarantee. Two jobs are sequential,never overlapping by design.

## Reporting

Primary:correct normally completed answers before scheduled deadlines per fixed observation minute. Show per-condition/per-block counts and common horizons first,then descriptive pooled results. Primary ablation islive vsarrival-only;fixed baselines remain contemporaneous. Report latency,tokens,deadline misses,caps,injection validity,actual queue occupancy,andinterventions. Arrival/fixed phases must have zero live-cut events;admission budgets are audited from saved state.

Do not claim statistical significance from two blocks or treat40responses per policy as40independent questions. Shared queues couple request outcomes. If arrival matches live's success and cost,prefer the simpler mechanism absent another benefit. If live only improves latency/tokens while matching goodput,report that distinction. If results reverse between blocks,report instability rather than choosing a favorable block. Larger/fresh validation remains conditional and is not automatically launched.

All raw outputs,executed sources,trace hashes,versions and scheduler/worker logs persist. Analyze failures and retain planned84/80/4denominators per block. No scientific request is killed merely for missing a deadline. Manual status checks only;monitor remains disabled.

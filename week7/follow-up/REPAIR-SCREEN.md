# Single-reviewer exploratory repair screen

The calibrated GPT-5.4 mini completed the bounded 48-attempt screen. The earlier two-reviewer calibration failure remains separate. The study used the same 24 paired questions and unchanged rubric, prompt and GPT settings. All 48 attempt records were sealed before joining continuation labels. The study does not estimate inter-reviewer reliability.

| Outcome | Count |
| --- | ---: |
| Ready | 5 |
| Localized repair | 6 |
| Unlocalized | 11 |
| Uncertain | 0 |
| Invalid or no judgment | 26 |
| Sibling pairs ordered | 1 of 24 |
| Sibling pairs abstained | 23 of 24 |

Of the 26 invalid attempts, 20 failed the verbatim-evidence check, five contained invalid JSON escape sequences, and one returned HTTP 400 without usable token accounting. These are observed operational failures. No text was repaired or normalized and no requests were retried.

| Held-out outcome draws | Informative ordered pairs | Correct | Incorrect | Ties | Concordance, exact 95% interval |
| --- | ---: | ---: | ---: | ---: | --- |
| 0–3 | 1 | 0 | 1 | 0 | 0%, 0–97.5% |
| 4–7 | 1 | 0 | 1 | 0 | 0%, 0–97.5% |

The same 2021-I-10 sibling pair was informative in both halves. The localized trajectory went from 0/4 short to 0/4 long in each half, while the unlocalized sibling went from 0/4 to 1/4 in each. Large empirical differences on other questions were left unranked, including 2022-II-7, where both judgments were invalid despite observed within-question benefit gaps of 100 and 50 percentage points. Descriptively, the six accepted localized prefixes averaged +22.9 points across eight draws per arm versus +6.8 for unlocalized and +5.0 for ready. These are unmatched groups, subject to selection from high invalidity, and cannot establish trajectory discrimination.

The operational screen fails the eight-pair coverage target. The single ordering is unfavorable and far too imprecise to decide whether the underlying repair signal predicts marginal benefit. Passing synthetic calibration did not translate into reliable grounding on real 4K prefixes. Stop this configuration. Any future work on recovery evidence needs a different way to verify cited steps before predictive evaluation.

The 47 attempts with usable accounting totaled 207,635 input and 15,108 output tokens (6,939 reasoning). Usage priced at the frozen rates was $0.22371225. The HTTP 400 retained a $0.015216 reservation. The study added $0.23892825 in ledger commitments and closed at $0.70188375 of $5. The sealed judgments and detailed per-case results are retained in the private execution archive.

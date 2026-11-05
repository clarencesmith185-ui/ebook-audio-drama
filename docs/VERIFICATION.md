# What a successful check means

| Check | Establishes | Does not establish |
|---|---|---|
| Source SHA and contiguous spans | Complete normalized input, unchanged/order-preserved | Audible word accuracy |
| Role review and canonical IDs | Operator-recorded cast decisions | Automatic correctness of all attributions |
| Reference WAV SHA | Exactly the retained reference bytes | No audible voice drift |
| Per-segment audio signature | Checkpoint bound to segment/voice/config | Good pronunciation |
| Finite nonempty samples | Audio exists and is numerically valid | No repetition, missing words or unwanted sounds |
| Episode export PCM reconstruction | WAV parts partition the unchanged speech master, without missing/duplicated frames | Exact target lengths, audible word accuracy or MP3 losslessness |
| Duration heuristic | A candidate for inspection | Proof of a bad or correct segment |
| Private Kaggle metadata | Requested visibility at packaging time | Actual account visibility or successful execution |

Before release, inspect names, numbers, short replies, long narration and transitions. Compare speech against original source text; use ASR alignment as another signal, not unquestionable truth. Keep unverified output labeled as such.

GPU determinism is not promised across devices, dependency versions or model updates. The renderer records the requested model revision and basic runtime environment. For reproducible experiments, use an upstream commit revision and retain the full environment lock. Default `main` is convenient but **not frozen**. Kaggle bootstrap dependencies are currently unpinned; verify and freeze a working environment before production use.

This repository has no automatic repair loop. Do not relax source checks to accommodate a bad generation. Preserve previous outputs and deliberately version replacements.

# Background sound workflow

Speech generation and sound design are separate stages. Preserve the repaired lossless voice master; do not regenerate voices to add atmosphere. This workflow packages **TangoFlux** for private Kaggle inference and mixes the returned sounds locally. Packaging never uploads or launches.

## 1. Review a source-grounded plan

Copy `examples/sound-plan.json`. Set the master SHA-256 and integer start/end frames for the selected part. Supported masters are mono PCM16 WAV; timings in `cues` are relative to that slice, in seconds. Frame range is half-open. Never derive times from an older, unrepaired render.

Each asset has a unique safe ID, English prompt, integer seed and duration in (0,30] seconds. Each cue references an asset, `ambience` or `foley`, start/end, positive `below_speech_db`, and source evidence. Reuse the same saved asset for recurring props. Within-utterance proportional timing is an estimate, not word alignment. Keep read-aloud notes dry. Do not add machinery to abandoned buildings, driving noise to parked cars, sirens, invented dialogue or sound merely because an object is mentioned.

## 2. Generate only sounds remotely

```sh
python -m pip install -e '.[sound]'
epub-drama sound-package examples/sound-plan.json YOUR_USERNAME/demo-sounds runs/sounds-v1
# Inspect run.py, kernel-metadata.json and payload-manifest.json.
kaggle kernels push -p runs/sounds-v1
kaggle kernels status YOUR_USERNAME/demo-sounds
# Once complete, retrieve only intended outputs:
kaggle kernels output YOUR_USERNAME/demo-sounds -p runs/sounds-v1/output --file-pattern 'assets/.*'
```

Replace the uppercase username placeholder with your lowercase account. The new notebook is private, GPU-enabled and receives **only IDs, prompts, durations and seeds**: no EPUB, voice references, master audio or evidence text. Review prompts themselves for private information. Uses pinned TangoFlux source commit `164420faa2b3f8a28bb013ccde7006422a616fc7` and checkpoint revision `367005e963cb3a9fb2e03a46104d7de23e34ceea`. Dependent encoder downloads are upstream-managed and not independently revision-pinned; this is not a completely hermetic runtime.

The isolated Python 3.11 environment avoids the upstream torch2.4/Python3.13 incompatibility. Interpreters, virtualenvs, pip/uv/HF caches and renderer live under `/tmp`, **not `/kaggle/working`**. Only sound assets and their manifest are exported. Raw finite waveforms are normalized to at most 0.90 before PCM24 saving: lowering the volume of an already clipped WAV cannot repair it.

Status refers to the current notebook session. Some CLI versions ignore a version suffix for output downloads; preserve the exact source and bind returned prompts/seeds/hashes to the payload manifest instead of assuming a version-named directory proves provenance. Poll at sensible intervals, not a tight loop. No automatic monitor is included.

## 3. Review and mix

Listen to generated assets for unwanted words/music, identity, period fit, artifacts and loop repetition. Approve exact hashes in a JSON file such as `{"rain":{"approved":true,"sha256":"ACTUAL_WAV_HASH"}}`.

```sh
epub-drama sound-mix my-plan.json master.wav runs/sounds-v1/output/assets runs/mix-v1 --review approved.json
# For an explicitly experimental draft when listening is unavailable:
epub-drama sound-mix my-plan.json master.wav runs/sounds-v1/output/assets runs/mix-draft --unreviewed-draft
# A new revision can lift an inaudible background without changing voices:
epub-drama sound-mix my-plan.json master.wav runs/sounds-v1/output/assets runs/mix-v2 --unreviewed-draft --background-boost-db 6
```

Output directories must be empty, preserving older revisions. Outputs: `dry.wav`, `effects.wav`, `mix.wav`, 96kbps `mix.mp3`, hash/size manifest. Dry samples are checked bit-identical to the selected master slice; voice gain stays unity. Assets are hash/prompt/seed checked and resampled to the voice rate. Ambience loops use crossfades, with fades at scene transitions. Foley plays once and can be truncated by its cue end. Background alone is ducked to 0.4 during speech (~8dB).

`below_speech_db` is a pre-duck RMS target relative to the entire selected dry slice, including silence—not a perceptual loudness promise. Starting around 18–22dB below speech may be more audible than 28dB plus ducking; audition on the listener's device. Increase the background with a new revision when necessary. The mixer refuses insufficient headroom rather than compressing/limiting voices. MP3 is decoded and checked for finite samples and no full-scale peaks. Technical checks do **not** prove audible quality. Full-mix listening remains pending even after asset approval.

Send the new MP3 explicitly as a replacement after a revision; include bytes/hash and draft status. A local fix does not update a previously delivered copy. No chat credentials or delivery integrations are included.

## Validation status and terms

The isolated runtime/normalization/mixing approach was exercised in a separate private project. This cleaned reusable implementation has offline contract tests; its new Kaggle wrapper is not independently end-to-end validated. No private project assets are included. TangoFlux checkpoint terms checked during that work restricted use to **non-commercial research**; MIT here covers our code, not model weights. Recheck upstream terms for your intended use. Do not assume download access grants unrestricted redistribution.

## Submit directly with configured Kaggle credentials

Install `.[kaggle]`, set `KAGGLE_API_TOKEN` and `KAGGLE_USERNAME`, then run:

```sh
epub-drama sound-run examples/sound-plan.json
epub-drama kaggle-status /path/to/receipt.json
epub-drama kaggle-download /path/to/receipt.json
```

The run command prints a receipt path under `~/.local/state/ebook-audio-drama/`.
Only prompts/durations/seeds are uploaded, never the master or cue source
anchors. The notebook stays private and gets a unique name per run. Generated
assets still need manifest checks and listening review before mixing; completion
does not imply audible quality. See the README for configuration and receipts.

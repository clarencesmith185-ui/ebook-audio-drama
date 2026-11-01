# EPUB → Audio Drama

**The original words. A persistent voice for each person.**

A small, review-first Python workflow for turning an EPUB into a **full-cast, unabridged audiobook** with Qwen3-TTS. It preserves narration and dialogue tags rather than rewriting a novel into a screenplay.

```text
EPUB spine → normalized source → reviewed speaker spans → character/voice registry
                                                       ↓
                     chapter audio ← resumable GPU rendering ← immutable voice references
```

## What it does

- Extracts body text in EPUB spine order, retaining headings and notes.
- Builds quotation-review scaffolds. **It does not guess speakers automatically.**
- Keeps canonical character IDs separate from names, aliases and voice versions.
- Requires a source-supported role and a matching voice description before casting.
- Uses Qwen3-TTS **VoiceDesign → Base voice cloning**, retaining each reference WAV and transcript.
- Checks ordered source spans and hashes before speech generation.
- Saves per-segment audio/checkpoints and chapter-to-voice bindings; resumes matching runs.
- Packages a selected chapter for a **private Kaggle GPU notebook**, including only needed inputs.
- Imports returned voice references without losing other chapters' cast records.

**Status:** initial reference implementation. The underlying approach has been exercised in a separate private pilot/chapter workflow. This cleaned package has passed **13 offline contract tests**; its GPU path and Kaggle bootstrap have **not yet been end-to-end tested**. No book or generated voice samples from that private project are included.

## Quick start: original demo

Python 3.10+:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
epub-drama demo projects/demo
epub-drama validate projects/demo 001 --allow-planned
```

The demo is an original short café scene with three roles. Its voice references are deliberately **planned, not generated**. `--allow-planned` checks the text and casting contracts; it is not an audio-quality or render-readiness claim.

### Render the demo on Kaggle

```sh
epub-drama kaggle-package projects/demo 001 YOUR_USERNAME/epub-drama-demo runs/demo-v1 --design-missing
# Inspect run.py, kernel-metadata.json and payload-manifest.json first.
kaggle kernels push -p runs/demo-v1
kaggle kernels status YOUR_USERNAME/epub-drama-demo
# Once terminal, retrieve that exact version into its own directory:
kaggle kernels output YOUR_USERNAME/epub-drama-demo/1 -p runs/demo-v1/output
```

Set your real lowercase Kaggle username/slug in the command. Packaging does **not** upload anything; the separate `kaggle kernels push` does. `--design-missing` explicitly authorizes the generated notebook to create **only already-planned voices**, save their references, then render the selected chapter.

Retrieve the returned `project/` directory (usually under `output/epub-drama/project/`), preserve it and import its voice registry:

```sh
epub-drama import-voices projects/demo runs/demo-v1/output/epub-drama/project
```

Before the next chapter, reuse those locked references. For larger references, use `--reference-kernel OWNER/PREVIOUS_KERNEL` to mount prior notebook outputs instead of embedding them. Runtime SHA-256 checks require the exact expected WAV/FLAC files, even if Kaggle attaches a newer notebook version. Missing or changed references fail rather than creating replacement voices. Keep each uploaded source/version and downloaded output in a separate directory.

Kaggle limits source size; the packager rejects scripts at or above 1,000,000 bytes. No dataset, model, account or credential is bundled with this repository.

### Or use your own CUDA GPU

```sh
python -m pip install -e '.[tts]'
epub-drama voice-design projects/demo narrator-v1
epub-drama voice-design projects/demo maya-v1
epub-drama voice-design projects/demo eli-v1
epub-drama validate projects/demo 001
epub-drama render projects/demo 001
# Use the output path printed by render:
epub-drama mp3 projects/demo/runs/001/RUN_ID/chapter.wav chapter-001.mp3
```

Install a CUDA-compatible PyTorch build for your machine. MP3 export requires FFmpeg. CPU/ARM speech inference is not validated by this implementation. The default 1.7B models follow the upstream API; runtime, GPU memory and throughput depend on hardware and dependency versions. See [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS#voice-design-then-clone).

## Use your own EPUB

```sh
epub-drama extract /path/to/book.epub projects/my-book
```

Each EPUB spine document gets a directory under `chapters/`. **A spine document is not necessarily a logical chapter**: front matter, footnotes or a split chapter may occupy separate documents. Review `manifest.json` before rendering. Empty spine documents cannot be rendered.

1. Read the selected `source.txt`; do not rewrite it.
2. Edit `script.json`: assign every quotation to a canonical person ID or narrator if it is a sign/title/written quotation. Review unquoted speech, thoughts, nested quotations and dialogue tags too.
3. Add people to `cast.json` with their role, source evidence and matching voice description. Keep uncertain claims explicit; do not mark a role reviewed until resolved.
4. Record any contextual performance choices in `notes`; never present them as author-supplied speaker labels. Unresolved speaker IDs remain `null` and block rendering.
5. Plan each new voice. Use an original reference transcript in the same language:

```sh
epub-drama voice-plan projects/my-book person_01 person_01-adult-v1 \
  --language Chinese \
  --reference-text '清晨的街道渐渐热闹起来。今天还有许多事情需要弄清楚。'
```

6. Once every span has been checked, set `source_reviewed` to `true`, validate and package/render.
7. Listen and check the audio against the source before treating the chapter as finished.

See [the project format](docs/PROJECT_FORMAT.md), [casting guide](docs/CASTING.md) and [verification notes](docs/VERIFICATION.md).

## Fidelity and scope

“Verbatim” here means **exactly matching the extracted, whitespace-normalized source**, not byte-identical EPUB markup. Extraction joins body text nodes with spaces and collapses Unicode whitespace. It excludes document-head metadata and scripts/styles. This can introduce spacing around inline markup, and ruby pronunciation text or image-only content needs manual review. It does not silently remove narration, footnotes or dialogue tags.

Text equality, valid WAVs and reused reference hashes **do not prove** that TTS pronounced every word, retained the intended emotion or avoided voice drift. Pronunciation review, ASR alignment and listening remain separate tasks.

Not included yet: automatic reliable speaker attribution, a review GUI, automatic ASR-based repair, background-music/soundscape generation, scene-timed SFX mixing, M4B export or an automatic live-log monitor. Speech stays in a clean stem so atmosphere can be mixed later without regenerating voices.

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

CI runs offline contract tests on Python 3.10 and 3.12. GPU dependencies are imported only by GPU commands. Tests cover source fidelity, unresolved speakers, role review, reference tampering, cross-person voice ownership, EPUB spine order, scoped packaging and safe reference import.

## License

Code and the original demo: **MIT**. Model weights and third-party packages retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md). Supply text and reference audio you are entitled to process and publish. Project data, EPUBs, credentials and generated audio are ignored by default and are not part of this release.

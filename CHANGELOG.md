# Changelog

## 0.1.0 — initial prepared release

- EPUB spine extraction and explicit whitespace-normalization manifest.
- Human-reviewed quotation scaffolds and exact source-span validation.
- Role-first canonical character/voice registry and explicitly scoped age variants.
- Qwen3-TTS VoiceDesign/Base backend with immutable references and resumable segments.
- Private Kaggle payload builder, selected-input isolation and reference import.
- Original three-role demo, documentation, MIT license and offline CI tests.

Validation scope: installation, demo contracts and generated payload syntax tested locally; no end-to-end GPU test of this cleaned implementation yet. Automatic speaker identification, ASR repair and background effects are not implemented.

## Unreleased

- Add prompt-only pinned TangoFlux Kaggle packager, isolated Python3.11 and non-exported runtime caches.
- Add source-grounded sound plan, local voice-preserving mixer, safe PCM saving, manifest/peak checks and explicit background-gain revisions.
- Document asset listening review, draft status, model terms and output provenance limitations.

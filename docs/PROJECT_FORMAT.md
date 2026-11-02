# Project format

```text
project/
  manifest.json                 # EPUB and extracted-document hashes
  cast.json                     # global identity + voice registry
  chapters/001/source.txt        # immutable normalized source
  chapters/001/script.json       # reviewed source spans
  voices/person-adult-v1.wav     # retain the actual generated reference
  runs/001/<configuration-id>/   # audio, per-segment metadata, binding, progress, report
  ledger.json                   # per-chapter completed-run bindings
```

Projects belong outside the source repo or under its ignored `projects/` directory.

## Speaker spans

Offsets are Python Unicode character indexes, not UTF-8 byte offsets. Every source character must occur exactly once, in order. `text` must equal `source[start:end]`.

```json
{
  "source_sha256": "SHA256_OF_SOURCE_UTF8",
  "source_reviewed": true,
  "notes": [],
  "segments": [
    {"start": 0, "end": 6, "text": "Hello.", "speaker": "narrator"}
  ]
}
```

A source-review checkbox is an explicit assertion by the operator, not an automatic model confidence score. Quotation scaffolds are unreviewed and unresolved by default. An ambiguous speaker must stay `null`; validation then stops.

## Character record

```json
{
  "characters": {
    "person_01": {
      "name": "Maya",
      "aliases": [],
      "role": "Adult traveler responding to a train announcement",
      "evidence": [{"chapter": "001", "start": 20, "note": "Explicit dialogue attribution"}],
      "role_reviewed": true,
      "voice_description": "Adult female English voice, medium register, clear and measured.",
      "default_voice": "person_01-adult-v1"
    }
  },
  "voices": {}
}
```

`voice-plan` creates a versioned record with description, reference transcript, language, path and planned state. `voice-design` locks the actual WAV SHA-256. Voice generation refuses to overwrite an existing version or orphaned reference file. Back up references before removing any remote output.

## Age variants / aliases

Same person → same canonical ID, even when the name changes. A reused name does not imply the same person. Assign IDs scene by scene; never globally substitute ambiguous aliases.

A child/adult/older variant is a **new voice ID**, not a new person. Keep existing versions. Explicitly set `voice` on the relevant script span and add that chapter to the variant's `allowed_chapters`. A non-default variant without that scope fails validation. This scopes deliberate artistic aging; it does not automatically model ages.

## Checkpoints and imports

A run ID includes voice bindings, source/script hashes and renderer configuration. Per-segment signatures and audio hashes prevent reuse of changed audio. Matching completed segments are reused. Corrupt or half-written checkpoints stop rather than being silently replaced; retain them for diagnosis and use a distinct run/version when intentionally repairing.

`import-voices` validates every imported record and WAV hash before copying. It merges voice records into the existing cast without replacing unrelated characters. It does not automatically trust remote source edits, regenerate voices or declare listening verification complete.

## Optional execution preferences

`execution.json` at the project root accepts only non-secret preferences:

```json
{"backend": "kaggle", "kaggle": {"owner": "your-kaggle-username"}}
```

`backend` is `local` (default) or `kaggle`. `render --backend` overrides it.
Credentials stay in the official CLI's environment or supported files.
`--owner` overrides configuration; `KAGGLE_USERNAME` is the final fallback.
Reading config, validating, and packaging never starts a remote job.

# Optional LLM-assisted preparation

`llm-prepare` proposes characters, roles, voice descriptions, speaker spans and
source-supported background-sound cues. **It does not render audio, rewrite the
book, update the cast/script, or approve anything.** Manual preparation continues
to work without a provider or credentials. Both providers run from your local
machine, independently of the local/Kaggle **audio** backend.

## API-key provider

Use an OpenAI-compatible Chat Completions endpoint supporting JSON-object output:

```sh
cp examples/llm-api.json llm.local.json
# Edit model to an available model ID; optionally change base_url and api_key_env.
export OPENAI_API_KEY='your-api-key'
epub-drama llm-prepare projects/my-book 001 --config llm.local.json
```

The URL is the API prefix (typically ending in `/v1`), not `/chat/completions`.
HTTPS is required except for loopback HTTP endpoints. URL credentials, queries,
fragments and redirects are rejected. Keys are read from the named environment
variable, never from JSON config. No automatic retries or provider fallbacks are
made: an explicit new command is another provider call. API usage follows your
provider's billing/quota; a ChatGPT subscription is not used by this API backend.
Other API protocols and providers without JSON-object Chat Completions support
need their own adapter; this is not a universal API connector.

## Codex with ChatGPT subscription login

Install a recent official Codex CLI, then run `codex login` and select ChatGPT
sign-in on this machine. Choose a model available to your account:

```sh
cp examples/llm-codex.json llm.local.json
# Edit model to your available Codex model ID.
codex login
epub-drama llm-prepare projects/my-book 001 --config llm.local.json
```

The adapter invokes official `codex exec` using existing CLI authentication,
forces ChatGPT login and the OpenAI provider, and removes API-key environment
variables so it cannot silently fall back to API billing. It does not read,
extract, copy or upload the CLI's login tokens. Account eligibility, model access,
usage limits and subscription terms still apply; this does not create unlimited
API access or support other vendors' subscription logins.

A recent CLI must support `--ignore-user-config`, `--ephemeral`, `--output-schema`,
`--output-last-message`, and read-only sandboxing. The adapter ignores user config,
uses an empty temporary working directory, sends the prompt on stdin (not process
arguments), and requests strict schema output. Only a small runtime environment
allowlist is inherited. It uses a read-only sandbox, **not** an operating-system
container or a guarantee that Codex cannot read other local files. Use a dedicated
OS account/container when that stronger boundary is needed. No source commands or
tools are needed for this task. Authentication stays in the CLI's normal store.

Official OpenAI documentation:
[non-interactive mode](https://developers.openai.com/codex/noninteractive),
[authentication](https://learn.chatgpt.com/docs/auth), and
[Chat Completions API](https://platform.openai.com/docs/api-reference/chat/create).

## Review and apply manually

Default output: `PROJECT/llm-review/001.suggestions.json`. Choose a fresh path with
`--output another-review.json`; existing files are never replaced. The artifact
contains source SHA-256, provider/model provenance, `UNREVIEWED_SUGGESTIONS`, and
`source_reviewed: false`. It is deliberately **not** a renderable script or cast.

1. Check the artifact hash against the unchanged chapter source. Offsets are
   zero-based Python Unicode character indexes, end-exclusive, not UTF-8 bytes.
2. Review each identity, evidence span and voice description. Keep canonical IDs
   consistent across chapters; evidence bounds do not prove a role is correct.
3. Copy only reviewed speaker assignments to `script.json`, and reviewed roles
   and voice descriptions to `cast.json`, following [casting](CASTING.md).
   Do not replace existing locked voices with new suggestions.
4. Sound cues identify **text spans, not audio timestamps**. After speech is
   rendered, build/review a timed [sound plan](SOUND_DESIGN.md) manually.
5. Run normal validation, voice planning/rendering and listening review. LLM
   suggestions never set source/role/audio approval flags for you.

Input is limited to 40,000 Unicode characters per chapter. Oversize chapters fail
before a provider call; there is no silent truncation or automatic chunking.
`timeout_seconds` accepts 1–900 (default 180). Malformed JSON, unknown fields,
duplicate character IDs, unknown speakers, incomplete/gapped/overlapping segments,
or out-of-bounds evidence/cues fail without writing an artifact. A source change
during the request also fails. Errors omit provider bodies and CLI transcripts.
These structural checks do not verify audible quality or semantic attribution.

## Data and credentials

Only the selected chapter source and existing cast IDs/name/role/voice-description
context are sent to the selected provider. No book-wide source, voice WAVs,
reference transcripts, project credentials or private project directory is
attached. This is still disclosure of that chapter to your chosen LLM provider;
use a provider appropriate for your material.

Keep per-machine settings in ignored `llm.local.json` and secrets in environment
variables/CLI login. The Kaggle speech payload explicitly selects source/script,
required cast/voices and package code: LLM settings, suggestions and login stores
are not included. LLM calls stay local even when speech uses Kaggle. The library
code itself contains no credentials. Avoid putting secrets into book text or cast
metadata. The implementation has offline mocked coverage only; provider account,
CLI authentication, quotas and live model compatibility require your own test.

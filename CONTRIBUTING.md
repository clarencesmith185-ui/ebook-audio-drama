# Contributing

Run the offline tests before proposing changes. Add regression coverage for fidelity, identity, checkpoint or packaging changes. Do not commit EPUBs, voice recordings, model weights, credentials or private project data.

Keep changes to extracted wording separate from rendering fixes. Speaker labels must stay reviewable. Never silently turn unknown dialogue into narrator speech or regenerate a locked reference.

GPU results should include model revision, dependency versions, device, source/config hashes and the scope of listening/ASR verification. Do not label a text-only test as audio validation.

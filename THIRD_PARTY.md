# Third-party components

- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS): external speech model/library; loaded at runtime, not redistributed here. VoiceDesign → Base cloning follows its documented public API. Check the selected model card and upstream license when downloading weights.
- PyTorch, NumPy and SoundFile: optional external runtime dependencies. No vendored weights or wheels.
- FFmpeg: optional external executable for MP3 conversion, installed separately.
- Kaggle CLI: optional external tool. This project prepares inputs but does not store credentials, call upload APIs or automatically launch notebooks.

The code in this repository was written for this workflow. The demo scene and reference text are original project examples. No third-party novel, private account slug, real-person voice reference, generated book audio, session history or API key is included.

- [TangoFlux](https://github.com/declare-lab/TangoFlux) and its [checkpoint card](https://huggingface.co/declare-lab/TangoFlux): optional sound generation backend, downloaded remotely, not redistributed. Checkpoint terms restrict non-commercial research use; review current terms. SciPy is an optional resampling dependency.

# Model files (not committed: `*.onnx` and `*.bin` are git-ignored)

| File | Role | Source |
|---|---|---|
| `nemo_en_titanet_small.onnx` | **Default speaker embedding** (192-dim) | https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx |
| `wespeaker_en_voxceleb_resnet34_LM.onnx` | Previous default (256-dim); kept for rollback and the benchmark | same release |
| `wespeaker_en_voxceleb_resnet293_LM.onnx`, `3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx` | Benchmark candidates only (`eval/voice_bench.py`) | same release |

Speech and language models are not stored here: faster-whisper downloads its models to `~/.cache/huggingface`, and Ollama holds
`qwen3.5:4b-mlx`, `gemma4:12b-mlx` and `nomic-embed-text`. Switching the speaker model re-derives nothing: people enrolled with another
model are asked to record again (their old samples stay in the database).

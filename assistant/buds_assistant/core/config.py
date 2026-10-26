"""Configuration for Sidekick. Defaults work out of the box; override in sidekick.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]                  # buds_assistant/
HERE = PKG.parent                                          # the assistant/ folder in a checkout
CHECKOUT = (HERE / "run.sh").exists()                      # running from the repository, not from a pip/pipx install
CONFIG_DIR = PKG / "config"                                # default settings and gestures ship inside the package
# Where the user's own files live: next to the code in a checkout, in Application Support when installed.
APP_HOME = HERE if CHECKOUT else Path.home() / "Library" / "Application Support" / "Buds Sidekick"
MODELS_DIR = HERE / "models" if CHECKOUT else APP_HOME / "models"
SPEAKER_MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx"


def simulator_dir(d: Path) -> Path:
    """The simulator must never write into the real data folder (its synthetic demo voices once answered for a real person)."""
    return d.with_name(d.name + "-sim")


@dataclass
class Config:
    data_dir: Path = APP_HOME / "data"
    # capture / replay
    ring_seconds: float = 8.0                    # replay window (5-60)
    # speaker identity
    speaker_model: Path = MODELS_DIR / "nemo_en_titanet_small.onnx"          # ~4x fewer errors than WeSpeaker ResNet34 on the voice bench (docs/validation/voice-eval.md)
    speaker_threshold: float = 0.45              # cosine (TitaNet scale); below = unknown. Real own-voice scores on two mics ran 0.45-0.79, other voices 0.14-0.22
    min_identify_seconds: float = 1.2           # shorter clips are too thin to name anyone from
    self_min_confidence: float = 0.0             # 0 = automatic: the match threshold + 0.06; a voice only counts as YOU (for gating hints/interpreter) at this score
    similar_voice_warning: float = 0.6           # warn at enrolment when two voiceprints are this similar
    keep_unnamed_days: int = 7                   # voices heard but not named are kept this long (a clip, no transcript of Telugu) so People can ask who they are; 0 = never
    store_unknown: bool = False                  # unknown speakers are never persisted by default
    # models (Ollama)
    ollama_host: str = "http://localhost:11434"
    chat_model: str = "gemma4:12b-mlx"          # ONE resident model for answers, judgement, memory and translation: a 16 GB Mac holds one big model, not two
    deep_model: str = "gemma4:12b-mlx"
    translate_model: str = "gemma4:12b-mlx"      # only model that got en->te right in our test (same as chat_model: Translate needs no loading)
    embed_model: str = "nomic-embed-text"
    whisper_model: str = "small.en"
    # voices (macOS `say`)
    voice_en: str = "Samantha"
    voice_te: str = "Geeta"
    # auto mode
    hint_min_gap: float = 8.0
    hints_per_hour: int = 40
    hint_max_words: int = 20
    hint_ttl: float = 6.0
    preload_translator: bool = True             # load the Telugu recogniser and warm the translator at start (needs chat_model == translate_model)
    judge_context_turns: int = 12               # how much of the conversation Autopilot's judgement reads
    judge_model: str | None = None              # None = the everyday chat model
    answer_stale_s: float = 20.0                # an answer older than this is shown but never spoken (the question was long forgotten)
    ask_timeout: float = 12.0                   # seconds to wait for a question while live
    identity_cue_gap: float = 600.0
    autopilot_sensitivity: str = "proactive"     # quiet | balanced | proactive
    autopilot_categories: list | None = None     # explicit list of enabled triggers; None = from sensitivity
    self_name: str = "Me"                       # the wearer's enrolled voice name (separates you from others)
    telugu_stt: bool = False                     # Telugu speech recognition (Telugu-tuned Whisper); off = English only
    telugu_model: str = "ukta-app/whisper-telugu-ct2"
    live_translation: bool = True                # live voice Translate (set false to hide it; typed/spoken "translate ..." always works)
    interpreter_from: str = "te"                 # the language they speak: te | en
    interpreter_to: str = "en"                   # the language you hear in your ears: en | te
    interpreter_two_way: bool = False            # also speak your English as Telugu on the Mac speakers
    interpreter: bool = False                    # whisper an English translation of Telugu speech into your ear
    # buds button map: touch-and-hold normally toggles noise mode behind our back. The command allowlist has no "do nothing"
    # option (voice_assistant | noise_control | volume), so remapping is OFF until verified on hardware (docs/validation/phase0-v2.md #5).
    button_remap: bool = False
    hold_remap_left: str = "voice_assistant"
    hold_remap_right: str = "voice_assistant"
    # placement
    placement: str = "auto"                      # auto | ear | remote
    ear_output_hint: str = "buds"               # output device whose name contains this plays the in-ear route (the Mac default may be the speakers)
    remote_output_hint: str = "speakers"         # substring of the output device used in remote mode
    # privacy
    audio_retention_days: int = 0                # 0 = never keep raw audio

    def is_you(self, score: float) -> bool:
        """A voice matched as the wearer counts as you a little above the match threshold (which calibration sets)."""
        return score >= (self.self_min_confidence or self.speaker_threshold + 0.06)

    @classmethod
    def load(cls, path: Path | None) -> "Config":
        c = cls()
        if path and Path(path).exists():
            doc = yaml.safe_load(Path(path).read_text()) or {}
            names = {f.name: f for f in fields(cls)}
            for k, v in doc.items():
                if k in names:
                    setattr(c, k, Path(v) if isinstance(getattr(c, k), Path) else v)
        c.data_dir = Path(c.data_dir)
        c.ring_seconds = min(max(float(c.ring_seconds), 5.0), 60.0)
        return c

    def public(self) -> dict:
        return {f.name: (str(getattr(self, f.name)) if isinstance(getattr(self, f.name), Path) else getattr(self, f.name))
                for f in fields(self)}

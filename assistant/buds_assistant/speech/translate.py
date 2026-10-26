"""English <-> Telugu translation with a local LLM (gemma4:12b was the only local model that got en->te right)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from buds_assistant.intelligence.llm import LLMError

NAMES = {"en": "English", "te": "Telugu"}
_TELUGU = re.compile(r"[ఀ-౿]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_lang(text: str) -> str:
    te, en = len(_TELUGU.findall(text)), len(_LATIN.findall(text))
    if te == 0 and en == 0:
        return "unknown"
    return "te" if te >= en else "en"


@dataclass
class TranslationResult:
    text: str
    src: str
    dst: str
    ok: bool
    error: str | None = None


def _chunks(text: str, limit: int = 300) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?।])\s+|\n+", text) if p.strip()]
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) + 1 > limit:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    return out


class Translator:
    def __init__(self, llm, model: str = "gemma4:12b-mlx") -> None:
        self.llm, self.model = llm, model

    def translate(self, text: str, src: str = "auto", dst: str | None = None) -> TranslationResult:
        text = (text or "").strip()
        if not text:
            return TranslationResult("", src, dst or "", False, "empty input")
        if src == "auto":
            src = detect_lang(text)
        if src == "unknown":
            return TranslationResult("", src, dst or "", False, "could not tell the language")
        dst = dst or ("en" if src == "te" else "te")
        if dst not in NAMES or src not in NAMES:
            return TranslationResult("", src, dst, False, "only English and Telugu are supported")
        if src == dst:
            return TranslationResult(text, src, dst, True)
        out = []
        for ch in _chunks(text):
            prompt = (f"Translate the following {NAMES[src]} text to {NAMES[dst]}. Keep people's names and numerals exactly, but translate everything else, including weekdays, months and times of day. "
                      f"Reply with only the translation, nothing else.\n\n{ch}")
            try:
                r = self.llm.chat([{"role": "user", "content": prompt}], model=self.model, max_tokens=300, temperature=0.1)
            except LLMError as exc:
                return TranslationResult("", src, dst, False, str(exc))
            r = r.strip().strip('"“”')
            out.append(r)
        res = " ".join(out).strip()
        if dst == "te" and not _TELUGU.search(res):
            return TranslationResult(res, src, dst, False, "model did not answer in Telugu")
        return TranslationResult(res, src, dst, bool(res))

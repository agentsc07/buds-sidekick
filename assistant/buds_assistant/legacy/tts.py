"""Text to speech. macOS `say` (offline, built in). Audio plays on the default output (the buds, if connected)."""
from __future__ import annotations

import asyncio
import shutil
from typing import Protocol


class TTS(Protocol):
    async def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...


class SayTTS:
    def __init__(self, voice: str | None = None, rate: int = 185) -> None:
        if not shutil.which("say"):
            raise RuntimeError("macOS `say` not found; use --tts print")
        self.voice, self.rate = voice, rate
        self._proc: asyncio.subprocess.Process | None = None

    async def speak(self, text: str) -> None:
        cmd = ["say", "-r", str(self.rate)] + (["-v", self.voice] if self.voice else []) + ["--", text]
        self._proc = await asyncio.create_subprocess_exec(*cmd)
        try:
            await self._proc.wait()
        except asyncio.CancelledError:
            self.stop()
            raise

    def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
            except ProcessLookupError:
                pass


class PrintTTS:
    async def speak(self, text: str) -> None:
        print(f"   [speaks] {text}")

    def stop(self) -> None:
        pass

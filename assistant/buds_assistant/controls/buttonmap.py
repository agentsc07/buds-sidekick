"""Remap the buds' touch-and-hold so it does not toggle noise mode behind our back, and always put it back."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Awaitable, Callable


class ButtonMapGuard:
    def __init__(self, path: Path, send: Callable[[str, str], Awaitable[None]], events) -> None:
        self.path, self.send, self.events = Path(path), send, events

    def _save(self, left: str, right: str) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"left": left, "right": right}))
        os.replace(tmp, self.path)

    async def apply(self, cur_l: str, cur_r: str, tgt_l: str, tgt_r: str) -> None:
        if not self.path.exists():                 # only the user's real mapping is ever saved
            self._save(cur_l, cur_r)
        try:
            await self.send(tgt_l, tgt_r)
        except Exception as exc:  # noqa: BLE001
            self.events.publish("error", where="buttonmap", error=repr(exc))

    async def restore(self) -> None:
        if not self.path.exists():
            return
        orig = json.loads(self.path.read_text())
        try:
            await self.send(orig["left"], orig["right"])
            self.path.unlink()
        except Exception as exc:  # noqa: BLE001  keep the file so the next start retries
            self.events.publish("error", where="buttonmap", error=repr(exc))

    async def recover(self) -> None:
        await self.restore()

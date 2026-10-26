# Sidekick v2, Phases 0 to 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the v1 prototype to a smooth, legible base (five modes, one gesture map, earcons, model residency, button-map safety, push UI state) and make Autopilot actually speak, with a decision log that explains every silence.

**Architecture:** Refactor `modes.py` into a five-mode `ModeManager`, add small focused modules (`touchfilter`, `context`, `earcons`, `models`, `buttonmap`, `uistate`, `commitments`), and turn `policy.py` into an `AutopilotEngine` (`autopilot.py`) that logs every candidate (said / noted / held back + reason). Phases 0 to 2 are headless-testable with the existing fakes. Phase 3 is the Dashboard v2 product UI (Preact + htm, vendored, no build step) driven by the pushed `UiState`; it is the main differentiator, so it gets the same rigor: API tests plus a recorded browser verification.

**Tech Stack:** Python 3.12, asyncio, FastAPI, SQLite, numpy, pytest (`asyncio_mode = auto`), existing `budslab` protocol package for buds commands; frontend: Preact + htm (single vendored ES module file), plain CSS with design tokens, no Node.

**Spec:** `docs/specs/spec-v2.md` (read section 18 first: it records the code-verified findings and decisions that override earlier sections).

**Not in this plan (separate plans, written when we get there):** Phase 4 voice commands + Recording + encryption, Phase 5 Interpreter pipeline, Phase 6 intelligence pass, Phase 7 packaging. This plan only creates the `interpreter` *mode* as a state with its side effects, not the voice-to-voice pipeline.

## Global Constraints

- All commands run from `assistant/` with `../.venv/bin/python -m pytest -m "not slow"`. Baseline before starting: 102 tests pass. Never leave them red between tasks.
- Five modes, exact names: `standby`, `listen`, `autopilot`, `interpreter`, `private`. Memory levels: `live`, `remember` (default), `recording`.
- Old mode names `idle`, `manual`, `conversation`, `auto` are removed from code, tests and JS in Task 4 (no aliases left behind except `ModeController = ModeManager`).
- Gesture slots (spec 4.2): L single=ask, L double=replay, L triple=private, L hold=interpreter, R single=mark, R double=autopilot, R triple=who, R hold=listen. Same map for ear and remote.
- Anti-accident filter: ignore touches within 1 s of a wear change; ignore a burst of more than 3 non-hold touches in 1 s.
- Contextual windows: whisper 4 s, noted commitment 5 s, replay 6 s. Precedence: speaking > whisper > noted > replay > base map.
- Autopilot: at most 1 hint / 20 s (`hint_min_gap`), 12 / hour, hint max 12 words (A2: 20), stale after 6 s, never while the wearer is speaking, never about unknown voices, off in `private` and `interpreter`.
- Sensitivity: `quiet` = capture + question; `balanced` (default) = capture, question, identity, commitment, mention; `proactive` = balanced (A6/A7 are "Later", not built here).
- Privacy: unknown voices never persisted; button map restored on exit and after a crash; every mode change audited (`store.audit`).
- Buds commands only through the existing allowlist (`budslab.protocol.commands.build` + `check_tx_id`).
- Commit after every task. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01ShmSf5jFUAWvWs7S8ayWnY`. (The project is not a git repo yet: Task 0 runs `git init`.)

## Review Focus

Failure modes the spec implies that no single task's happy path covers; each has a test in the owning task.

1. Touch burst from a pocket (5 taps in 1 s) must fire nothing, but a normal hold (event burst) must still toggle once. (Task 2)
2. Double-tap right after a whisper dismisses it and must NOT toggle Autopilot; the same double 5 s later must toggle it. (Task 3)
3. Leaving `private` must land in `standby`, never straight back into a listening mode; entering `interpreter` pauses autopilot and exiting restores it. (Task 4)
4. Crash after remapping the buds: next start restores the saved mapping before doing anything else; a second `apply` must not overwrite the saved original with our own remap. (Task 7)
5. Autopilot on a cold start (only "Me" enrolled, no facts) still yields commitment captures, and a whisper that becomes stale (6 s) or collides with the wearer speaking is dropped with a logged reason, not silently. (Tasks 9, 10)

---

## File Structure

| File | Responsibility |
|---|---|
| `assistant/sidekick_gestures.yaml` | Single v2 gesture map (modified) |
| `assistant/buds_assistant/touchfilter.py` | Anti-accident filter (new) |
| `assistant/buds_assistant/context.py` | Contextual gesture windows (new) |
| `assistant/buds_assistant/modes.py` | `ModeManager`: five modes, memory level, placement, dispatch (rewrite) |
| `assistant/buds_assistant/earcons.py` | Designed sound set, pre-rendered (new) |
| `assistant/buds_assistant/output.py` | Add `earcon()` (modify) |
| `assistant/buds_assistant/models.py` | `ModelManager` residency + readiness (new) |
| `assistant/buds_assistant/llm.py` | `pinned` models, FakeLLM records keep_alive (modify) |
| `assistant/buds_assistant/buttonmap.py` | `ButtonMapGuard` (new) |
| `assistant/buds_assistant/uistate.py` | `UiState` reducer + snapshot (new) |
| `assistant/buds_assistant/store.py` | `autopilot_decisions` table (modify) |
| `assistant/buds_assistant/commitments.py` | Rule-based commitment detector (new) |
| `assistant/buds_assistant/autopilot.py` | `AutopilotEngine` (new, from `policy.py`) |
| `assistant/buds_assistant/policy.py` | Re-export shim (`Policy = AutopilotEngine`) |
| `assistant/buds_assistant/segmenter.py`, `pipeline.py` | `speaking` signal (modify) |
| `assistant/buds_assistant/sidekick.py` | Delivery, handlers, wiring (modify) |
| `assistant/tests/fixtures_autopilot.py` | Labelled scripted conversation (new) |
| `docs/validation/phase0-v2.md` | Findings + real-hardware checklist (new) |

---

### Task 0: Baseline, git, Phase 0 findings

**Files:**
- Create: `docs/validation/phase0-v2.md`
- Create: `.gitignore`

- [ ] **Step 1: Baseline**

Run: `cd assistant && ../.venv/bin/python -m pytest -m "not slow" -q`
Expected: `102 passed` (if not, stop and report).

- [ ] **Step 2: Init git**

```bash
cd .. && git init && printf '.venv/\n__pycache__/\n*.pyc\nassistant/data/\nlab/data/\nassistant/models/*.onnx\n' > .gitignore
git add -A && git commit -m "chore: baseline before v2 (v1 + specv2)"
```

- [ ] **Step 3: Write `docs/validation/phase0-v2.md`** with these sections, content taken from `docs/specs/spec-v2.md` 18.1: "Autopilot diagnosis (code-verified)" (the 4 findings), "Needs hardware, run in parallel" (checklist below), "Results" (empty table to fill):

```markdown
## Needs hardware (run in parallel, do not block Phase 1)
1. Do single/double/triple taps reach macOS as media keys? Pair buds, run `lab` Layer A, tap, record yes/no.
2. Mic comparison: someone speaks at 1 m; record via buds mic and Mac mic with `assistant/buds_assistant/eval/capture_kit.py`; compare with `speaker_bench`.
3. Speaker accuracy with 3+ real people (docs/validation/phase0.md).
4. Real Telugu: 3 speakers x 20 sentences, WER + meaning-preserved rating.
5. Hold remap: in the lab, set touchpad option, confirm the hold no longer toggles noise mode; confirm restore.
```

- [ ] **Step 4: Commit** `git add -A && git commit -m "docs: phase 0 findings and hardware checklist"`

---

### Task 1: Gesture map v2

**Files:**
- Modify: `assistant/sidekick_gestures.yaml`
- Test: `assistant/tests/test_gesture_map.py`

**Interfaces:**
- Produces: profiles `ear` and `remote` (identical) from `load_profiles`; action names `ask, replay, private_toggle, interpreter_toggle, mark, autopilot_toggle, who, listen_toggle`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from buds_assistant.gestures import GestureRecognizer
from buds_assistant.modes import load_profiles

GEST = Path(__file__).parent.parent / "sidekick_gestures.yaml"
TABLE = [("L:single", "ask"), ("L:double", "replay"), ("L:triple", "private_toggle"),
         ("R:single", "mark"), ("R:double", "autopilot_toggle"), ("R:triple", "who")]


@pytest.mark.parametrize("profile", ["ear", "remote"])
@pytest.mark.parametrize("token,action", TABLE)
def test_tap_map(profile, token, action):
    bindings, timeout, deb = load_profiles(GEST)[profile]
    r = GestureRecognizer(bindings, timeout, deb)
    got = r.feed(token, 10.0) or r.poll(10.0 + timeout + 0.01)
    assert [m.binding.action for m in got] == [action]


@pytest.mark.parametrize("profile", ["ear", "remote"])
@pytest.mark.parametrize("token,action", [("L:hold_start", "interpreter_toggle"), ("R:hold_start", "listen_toggle")])
def test_hold_toggles_once_per_burst(profile, token, action):
    bindings, timeout, deb = load_profiles(GEST)[profile]
    r = GestureRecognizer(bindings, timeout, deb)
    fired = [m for t in (0.0, 0.2, 0.5, 0.9) for m in r.feed(token, t)]
    assert [m.binding.action for m in fired] == [action]


def test_no_sequences_left():
    for profile in load_profiles(GEST).values():
        assert all(len(b.pattern) == 1 for b in profile[0])
```

- [ ] **Step 2: Run, expect FAIL** `../.venv/bin/python -m pytest tests/test_gesture_map.py -q` (old map has different actions).

- [ ] **Step 3: Replace `sidekick_gestures.yaml`**

```yaml
# Sidekick v2 gesture map. Same in the ear and as a remote (buds out). Left = talk to the assistant, right = control the session.
# Contextual gestures (stop / tell me more / not useful / undo / catch me up) are handled in context.py, not here.
sequence_timeout: 0.7
hold_debounce: 1.2

bindings:
  - {name: ask,         gesture: "L:single", action: ask}
  - {name: replay,      gesture: "L:double", action: replay}
  - {name: private,     gesture: "L:triple", action: private_toggle}
  - {name: interpreter, gesture: "L:hold", mode: toggle, action: interpreter_toggle}
  - {name: mark,        gesture: "R:single", action: mark}
  - {name: autopilot,   gesture: "R:double", action: autopilot_toggle}
  - {name: who,         gesture: "R:triple", action: who}
  - {name: listen,      gesture: "R:hold", mode: toggle, action: listen_toggle}
# remote_bindings omitted on purpose: load_profiles reuses `bindings` for the remote profile.
```

- [ ] **Step 4: Run, expect PASS** (the old `tests/test_gestures.py` uses its own yaml; leave it).

- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: single v2 gesture map for ear and remote"`

---

### Task 2: Anti-accident filter

**Files:**
- Create: `assistant/buds_assistant/touchfilter.py`
- Test: `assistant/tests/test_touchfilter.py`

**Interfaces:**
- Produces: `TouchFilter(burst_limit: int = 3, window: float = 1.0, wear_guard: float = 1.0)`, `.note_wear(now: float) -> None`, `.accept(token: str, now: float) -> bool`. Tokens containing `hold` always pass the burst check (a hold is naturally a burst) but still obey `wear_guard`.

- [ ] **Step 1: Failing tests**

```python
from buds_assistant.touchfilter import TouchFilter


def test_taps_within_guard_after_wear_change_are_ignored():
    f = TouchFilter()
    f.note_wear(10.0)
    assert not f.accept("L:single", 10.5)
    assert f.accept("L:single", 11.1)


def test_pocket_burst_is_ignored():
    f = TouchFilter()
    results = [f.accept("L:single", 20.0 + i * 0.2) for i in range(5)]    # 5 taps in 0.8 s
    assert results[:3] == [True, True, True] and results[3:] == [False, False]


def test_slow_taps_are_fine():
    f = TouchFilter()
    assert all(f.accept("R:double", t) for t in (1.0, 2.5, 4.0, 5.5, 7.0))


def test_hold_burst_passes():
    f = TouchFilter()
    assert all(f.accept("L:hold_start", 30.0 + i * 0.1) for i in range(8))
```

- [ ] **Step 2: Run, expect FAIL** (module missing).

- [ ] **Step 3: Implement**

```python
"""Anti-accident filter: ignore touches right after the buds are inserted/removed and bursts of taps (pocket / adjusting)."""
from __future__ import annotations

from collections import deque


class TouchFilter:
    def __init__(self, burst_limit: int = 3, window: float = 1.0, wear_guard: float = 1.0) -> None:
        self.burst_limit, self.window, self.wear_guard = burst_limit, window, wear_guard
        self._wear = float("-inf")
        self._taps: deque[float] = deque()

    def note_wear(self, now: float) -> None:
        self._wear = now

    def accept(self, token: str, now: float) -> bool:
        if now - self._wear < self.wear_guard:
            return False
        if "hold" in token:
            return True
        while self._taps and now - self._taps[0] > self.window:
            self._taps.popleft()
        self._taps.append(now)
        return len(self._taps) <= self.burst_limit
```

- [ ] **Step 4: Run, expect PASS.** **Step 5: Commit** `feat: touch anti-accident filter`.

---

### Task 3: Contextual gestures

**Files:**
- Create: `assistant/buds_assistant/context.py`
- Test: `assistant/tests/test_context.py`

**Interfaces:**
- Produces: `GestureContext`, `.open(kind: str, now: float) -> None` (kinds `"whisper"`, `"noted"`, `"replay"`), `.close(kind)`, `.intercept(gesture: str, now: float, speaking: bool) -> str | None` returning one of `"stop" | "tell_more" | "not_useful" | "undo_commitment" | "catch_up"` or `None` (= use the base map). `gesture` is `"L:single"`, `"R:double"` etc.

- [ ] **Step 1: Failing tests**

```python
from buds_assistant.context import GestureContext


def test_any_single_tap_stops_speech():
    c = GestureContext()
    assert c.intercept("R:single", 1.0, speaking=True) == "stop"
    assert c.intercept("R:double", 1.0, speaking=True) is None        # only singles stop


def test_whisper_window_single_and_double():
    c = GestureContext()
    c.open("whisper", 10.0)
    assert c.intercept("L:single", 12.0, False) == "tell_more"
    c.open("whisper", 10.0)
    assert c.intercept("R:double", 12.0, False) == "not_useful"       # does NOT fall through to autopilot toggle
    assert c.intercept("R:double", 12.5, False) is None               # window is consumed


def test_window_expires():
    c = GestureContext()
    c.open("whisper", 10.0)
    assert c.intercept("R:double", 14.5, False) is None               # > 4 s


def test_noted_window_double_undoes():
    c = GestureContext()
    c.open("noted", 20.0)
    assert c.intercept("L:double", 24.0, False) == "undo_commitment"
    c.open("noted", 20.0)
    assert c.intercept("L:double", 25.5, False) is None               # > 5 s


def test_replay_window_left_double_escalates():
    c = GestureContext()
    c.open("replay", 30.0)
    assert c.intercept("L:double", 35.0, False) == "catch_up"
    c.open("replay", 30.0)
    assert c.intercept("R:double", 35.0, False) is None


def test_precedence_speaking_beats_whisper():
    c = GestureContext()
    c.open("whisper", 40.0)
    assert c.intercept("L:single", 41.0, speaking=True) == "stop"
```

- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement**

```python
"""Short-lived gesture meanings (spec 4.3). Precedence: speaking > whisper > noted > replay > base map."""
from __future__ import annotations

TTL = {"whisper": 4.0, "noted": 5.0, "replay": 6.0}


class GestureContext:
    def __init__(self) -> None:
        self._open: dict[str, float] = {}

    def open(self, kind: str, now: float) -> None:
        self._open[kind] = now + TTL[kind]

    def close(self, kind: str) -> None:
        self._open.pop(kind, None)

    def _live(self, kind: str, now: float) -> bool:
        return self._open.get(kind, 0.0) >= now

    def intercept(self, gesture: str, now: float, speaking: bool) -> str | None:
        kind = gesture.split(":", 1)[1] if ":" in gesture else gesture
        side = gesture.split(":", 1)[0]
        if speaking and kind == "single":
            return "stop"
        if self._live("whisper", now):
            if kind == "single":
                self.close("whisper")
                return "tell_more"
            if kind == "double":
                self.close("whisper")
                return "not_useful"
        if self._live("noted", now) and kind == "double":
            self.close("noted")
            return "undo_commitment"
        if self._live("replay", now) and gesture == "L:double":
            self.close("replay")
            return "catch_up"
        return None
```

- [ ] **Step 4: PASS. Step 5: Commit** `feat: contextual gesture windows`.

---

### Task 4: ModeManager (five modes + memory level)

**Files:**
- Modify: `assistant/buds_assistant/modes.py` (rewrite `ModeController` into `ModeManager`)
- Modify: `assistant/buds_assistant/sidekick.py` (mode names, handlers dict), `assistant/buds_assistant/brain.py`, `assistant/buds_assistant/dashboard/server.py`, `assistant/buds_assistant/dashboard/web/app.js`, `index.html`, `assistant/tests/test_modes.py`, `test_pipeline_e2e.py`, `test_dashboard.py` and any other file the grep finds
- Test: `assistant/tests/test_modes.py` (rewrite)

**Interfaces:**
- Consumes: `TouchFilter` (Task 2), `GestureContext` (Task 3), `load_profiles` (existing).
- Produces: `MODES = ("standby","listen","autopilot","interpreter","private")`; `ModeManager(cfg, events, output, ring, pipeline, policy, store, source_factory, profiles, handlers=None, ambient=None)`; `.mode`, `.memory_level`, `.placement`; `async set_mode(mode)`, `async set_memory_level(level)`, `async dispatch(action, **kw)`, `async on_token(token, now)`, `async poll(now)`, `async on_wear(side, code)`; `.context: GestureContext`, `.touch: TouchFilter`; `.state()` returns `{"mode","memory_level","placement","route","conversation_id","ring_seconds","autopilot"}`. `ModeController = ModeManager` alias. Handler names it dispatches to `handlers`: `ask`, `who`, `catch_up`, `tell_more`, `not_useful`, `undo_commitment`.

Transition rules (implement exactly):
- `listen`: starts pipeline from `standby`; from `autopilot` just disables policy; from `interpreter` keep pipeline running (it is already capturing).
- `autopilot`: if not capturing, start pipeline first; `policy.enabled = True`; if previous was `interpreter`, error-free switch (interpreter off).
- `interpreter`: remember `_resume_autopilot = (prev == "autopilot")`; `policy.enabled = False`; `cfg.interpreter = True`; ensure pipeline capturing from `source_factory("remote")` (Mac mic) regardless of placement; ambient on if placement is ear.
- Leaving `interpreter` (to anything but `private`): `cfg.interpreter = False`; if `_resume_autopilot` and target is `listen` → go to `autopilot` instead.
- `private`: as v1 (stop output, stop pipeline without extract, clear ring, policy off, ambient off, `cfg.interpreter = False`). Leaving `private` always goes to `standby` regardless of the requested mode, and publishes the mode event once.
- `standby`: stop pipeline, ambient off, policy off, `cfg.interpreter = False`.
- `set_memory_level("recording")` only valid in `listen|autopilot|interpreter`; it audits `recording_start`. (Actual recording lands in Phase 4; here it only stores the level and audits.)
- Action mapping in `dispatch`: `listen_toggle` (listen/autopilot → standby, else listen), `autopilot_toggle` (autopilot → listen, else autopilot), `interpreter_toggle`, `private_toggle`, `replay` (if `standby`: say "Nothing to replay. Listen first."; else play ring and `context.open("replay", now)`), `mark` (as v1, plus earcon later), `stop`, `catch_up`/`who`/`ask`/`tell_more`/`not_useful`/`undo_commitment` via `handlers`.
- `_fire(m)`: build gesture string from `m.binding.pattern[0]` when `len(pattern)==1`; call `self.touch.accept` first (drop if False, publish `gesture_ignored`); then `context.intercept(gesture, now, self.output.busy)`; if it returns an action dispatch that and skip the base binding; else dispatch `m.binding.action`.
- `on_wear` also calls `self.touch.note_wear(time.monotonic())` whenever the placement code for a side changes.

- [ ] **Step 1: Find every old-name use**

Run: `cd assistant && grep -rn "\"idle\"\|\"auto\"\|\"conversation\"\|\"manual\"\|'idle'\|'auto'\|conversation_toggle\|auto_toggle\|capture_toggle\|private_toggle" --include=*.py --include=*.js --include=*.html . | grep -v "\.venv"`
Note the list; every hit is updated in Step 5.

- [ ] **Step 2: Rewrite `tests/test_modes.py`** keeping its `Src`, `FakePipeline`, `FakePolicy` helpers and `make()`; replace the tests with:

```python
async def test_both_buds_out_means_remote_placement_with_mac_audio(tmp_path):
    mc, pipe, out, ring, amb, ear, remote, ev, store = make(tmp_path)
    await mc.on_wear("L", 1); await mc.on_wear("R", 1)
    assert mc.placement == "ear"
    await mc.on_wear("L", 2); await mc.on_wear("R", 3)
    assert mc.placement == "remote" and out.route == "remote"


async def test_autopilot_from_standby_starts_listen_then_whispers(tmp_path):
    mc, pipe, out, ring, amb, *_ = make(tmp_path)
    await mc.on_wear("L", 1); await mc.on_wear("R", 1)
    await mc.set_mode("autopilot")
    assert pipe.log[0] == ("start", "buds-mic", "ear") and mc.policy.enabled and amb == [True]
    await mc.dispatch("autopilot_toggle")                      # off -> back to listen, mic stays on
    assert mc.mode == "listen" and not mc.policy.enabled and pipe.conv_id == 7


async def test_interpreter_pauses_autopilot_and_restores_it(tmp_path):
    mc, pipe, *_ = make(tmp_path)
    await mc.on_wear("L", 1); await mc.on_wear("R", 1)
    await mc.set_mode("autopilot")
    await mc.set_mode("interpreter")
    assert not mc.policy.enabled and mc.cfg.interpreter
    assert pipe.log[-1][1] == "mac-mic" or any(x[1] == "mac-mic" for x in pipe.log)   # Mac mic by default
    await mc.dispatch("interpreter_toggle")                    # off
    assert mc.mode == "autopilot" and mc.policy.enabled and not mc.cfg.interpreter


async def test_private_wins_and_returns_to_standby(tmp_path):
    mc, pipe, out, ring, amb, *_ = make(tmp_path)
    await mc.set_mode("autopilot")
    await mc.dispatch("private_toggle")
    assert mc.mode == "private" and not mc.policy.enabled and pipe.log[-1] == ("stop", False)
    await mc.dispatch("private_toggle")
    assert mc.mode == "standby"


async def test_replay_in_standby_says_listen_first(tmp_path):
    mc, pipe, out, *_ = make(tmp_path)
    await mc.dispatch("replay")
    assert any("Listen first" in x.get("text", "") for x in out.log)


async def test_every_mode_change_is_audited_and_published(tmp_path):
    mc, pipe, out, ring, amb, ear, remote, ev, store = make(tmp_path)
    await mc.set_mode("listen")
    assert store.audit_log()[0]["kind"] == "mode"
    assert ev.recent(types={"mode"})[-1]["data"]["mode"] == "listen"


async def test_pocket_burst_fires_nothing_but_hold_still_toggles(tmp_path):
    mc, pipe, *_ = make(tmp_path)
    for i in range(6):
        await mc.on_token("L:single", 50.0 + i * 0.1)
        await mc.poll(50.0 + i * 0.1 + 0.8)
    assert mc.mode == "standby"
    await mc.on_token("R:hold_start", 60.0); await mc.on_token("R:hold_start", 60.4)
    assert mc.mode == "listen"


async def test_double_tap_after_whisper_does_not_toggle_autopilot(tmp_path):
    mc, *_ = make(tmp_path)
    await mc.set_mode("listen")
    seen = []
    mc.handlers["not_useful"] = lambda **k: seen.append("nu") or __import__("asyncio").sleep(0)
    mc.context.open("whisper", 100.0)
    await mc.on_token("R:double", 101.0); await mc.poll(102.0)
    assert seen == ["nu"] and mc.mode == "listen"
    await mc.on_token("R:double", 110.0); await mc.poll(111.0)
    assert mc.mode == "autopilot"
```

(`make()` must pass `handlers={}` so the dict is mutable; `FakePolicy` gets `enabled = False` as instance attr.)

- [ ] **Step 3: Run, expect FAIL** (`ImportError: ModeManager` / mode names).

- [ ] **Step 4: Implement** `ModeManager` in `modes.py` per the rules above (keep `load_profiles`, `MODES` updated, add `ModeController = ModeManager`). Use `time.monotonic()` for gesture timing (`on_token(token, now)` receives it already) and `time.time()` only for bookmarks.

- [ ] **Step 5: Update every hit from Step 1** to the new names (`idle`→`standby`, `conversation`→`listen`, `auto`→`autopilot`, `manual` removed; Sidekick `_ask` checks `self.modes.mode in ("listen","autopilot","interpreter")`; Sidekick `_handlers()` adds `tell_more`, `not_useful`, `undo_commitment` stubs that publish an event and do nothing yet (Task 10 fills them) and drops `ask_toggle`, `translate_last`, `repeat`; the dashboard buttons/labels use the new names; `brain.py` reply actions `auto:on`→`autopilot:on` etc.; `Brain` still accepts the spoken phrases "auto mode on" and also "autopilot on").

- [ ] **Step 6: Full suite** `../.venv/bin/python -m pytest -m "not slow" -q` Expected: all pass (old count minus removed tests plus new ones). Fix anything red before moving on.

- [ ] **Step 7: Commit** `feat: ModeManager with five modes, contextual + filtered gestures`.

---

### Task 5: Earcons

**Files:**
- Create: `assistant/buds_assistant/earcons.py`
- Modify: `assistant/buds_assistant/output.py` (add `earcon`), `assistant/buds_assistant/modes.py` (play earcons on mode on/off and gesture accepted)
- Test: `assistant/tests/test_earcons.py`

**Interfaces:**
- Produces: `NAMES: tuple[str, ...]`, `render(name: str, rate: int = 22050) -> np.ndarray` (int16, mono), `class Earcons` with `.get(name) -> tuple[np.ndarray, int]` (cached), `OutputArbiter.earcon(name: str) -> None` (fire and forget; skipped if a higher-priority sound is busy, except `error`).

- [ ] **Step 1: Failing tests**

```python
import numpy as np

from buds_assistant.earcons import NAMES, Earcons, render
from buds_assistant.output import FakePlayer, FakeTTS, OutputArbiter


def test_all_names_render_short_soft_and_distinct():
    sigs = {}
    for n in NAMES:
        a = render(n)
        assert a.dtype == np.int16 and 0.05 < a.size / 22050 < 0.7
        assert np.abs(a).max() <= 0.45 * 32767                      # soft
        sigs[n] = a
    assert len({a.tobytes() for a in sigs.values()}) == len(NAMES)  # all different


def test_required_set_exists():
    for n in ("mode_on", "mode_off", "listen_start", "listen_stop", "accepted", "command", "whisper", "noted",
              "error", "reminder", "thinking", "never_mind"):
        assert n in NAMES


async def test_arbiter_plays_earcon_without_cutting_an_answer():
    p = FakePlayer()
    out = OutputArbiter(FakeTTS(), {"ear": p, "remote": FakePlayer()})
    out.earcon("accepted")
    await __import__("asyncio").sleep(0.05)
    assert len(p.played) == 1
    out._cur_task = __import__("asyncio").ensure_future(__import__("asyncio").sleep(0.2)); out._cur_prio = 3
    out.earcon("accepted")
    await __import__("asyncio").sleep(0.05)
    assert len(p.played) == 1                                         # skipped while an answer is playing
```

- [ ] **Step 2: FAIL. Step 3: Implement** `earcons.py`: each name is a tuple of `(freq_hz, ms)` notes rendered as sine with 8 ms attack and exponential decay, amplitude 0.3; e.g. `mode_on` = C5→E5 rising (523,90),(659,130); `mode_off` falling; `listen_start` single 700 Hz 100 ms; `listen_stop` 500 Hz; `accepted` 880 Hz 60 ms; `command` 988→1175; `whisper` 440 Hz 120 ms very soft (amp 0.18); `noted` 784→988; `error` 330→262 (two low notes); `reminder` 659 ×2; `thinking` 600 Hz 50 ms; `never_mind` 440→330. `render` sums notes with 15 ms gaps. `Earcons.get` caches. In `OutputArbiter.__init__` create `self.earcons = Earcons()`; implement:

```python
def earcon(self, name: str) -> None:
    if self.busy and name != "error":
        return
    audio, rate = self.earcons.get(name)
    asyncio.get_running_loop().run_in_executor(None, self.players[self.route].play, audio, rate)
    self._emit("earcon", name=name)
```

- [ ] **Step 4: Wire into `ModeManager`**: `mode_on` when entering listen/autopilot/interpreter, `mode_off` when returning to standby, `listen_start`… keep to mode on/off + `accepted` at the start of `_fire`. Replace the v1 `say("Marked.", "chime")` in `mark` with `earcon("noted")`. Add a spoken phrase after each mode change (`Listening`, `Autopilot on`, `Interpreter`, `Private`, `Standby`), max 3 words, priority `chime`.

- [ ] **Step 5: Full suite. Commit** `feat: designed earcon set and spoken mode confirmations`.

---

### Task 6: ModelManager (residency)

**Files:**
- Create: `assistant/buds_assistant/models.py`
- Modify: `assistant/buds_assistant/llm.py` (add `pinned`, FakeLLM records `keep_alive`), `assistant/buds_assistant/modes.py` (call `models.enter(mode)`), `assistant/buds_assistant/sidekick.py` (construct)
- Test: `assistant/tests/test_models.py`

**Interfaces:**
- Produces: `ModelManager(llm, cfg, events)`, `.state() -> dict[str, str]` with keys `chat, embed, translate` and values `"unloaded" | "loading" | "ready"`, `.enter(mode: str) -> None` (blocking, run in executor), `.leave(mode: str) -> None`. `OllamaClient.pinned: set[str]`, `FakeLLM.pinned`.
- Chat/embed are warmed at start and never unloaded; `translate_model` is loaded on entering `interpreter` (`keep_alive="30m"`, pinned) and unloaded on leaving (`keep_alive="0"`, unpinned).

- [ ] **Step 1: Failing tests**

```python
from buds_assistant.config import Config
from buds_assistant.events import EventBus
from buds_assistant.llm import FakeLLM
from buds_assistant.models import ModelManager


def test_chat_and_embed_ready_after_start():
    llm, ev = FakeLLM(), EventBus()
    m = ModelManager(llm, Config(), ev)
    assert m.state()["chat"] == "unloaded"
    m.start()
    assert m.state()["chat"] == "ready" and m.state()["embed"] == "ready" and m.state()["translate"] == "unloaded"


def test_interpreter_loads_translate_model_then_unloads():
    llm, ev, cfg = FakeLLM(), EventBus(), Config()
    m = ModelManager(llm, cfg, ev); m.start()
    m.enter("interpreter")
    assert m.state()["translate"] == "ready" and cfg.translate_model in llm.pinned
    assert llm.calls[-1]["model"] == cfg.translate_model and llm.calls[-1]["keep_alive"] == "30m"
    m.leave("interpreter")
    assert m.state()["translate"] == "unloaded" and cfg.translate_model not in llm.pinned
    assert llm.calls[-1]["keep_alive"] == "0"


def test_state_changes_are_published():
    ev = EventBus(); m = ModelManager(FakeLLM(), Config(), ev); m.start()
    assert ev.recent(types={"model_state"})


def test_llm_down_reports_unloaded_not_crash():
    m = ModelManager(FakeLLM(up=False), Config(), EventBus()); m.start()
    assert m.state()["chat"] == "unloaded"
```

- [ ] **Step 2: FAIL. Step 3: Implement.** In `llm.py`: `OllamaClient.__init__` adds `self.pinned: set[str] = set()` and the keep logic becomes `keep_alive or ("30m" if model in (None, self.chat_model) or model in self.pinned else "90s")`; `FakeLLM.__init__` adds `self.pinned = set()` and `calls.append({"messages":..., "model":..., "keep_alive": keep_alive})`. `ModelManager.start()` runs `llm.warm()` inside try/except `LLMError`, sets states, publishes `model_state`. `enter`/`leave` as described (a `chat(..., max_tokens=1, keep_alive=...)` call; catch `LLMError` → state `"unloaded"` and publish `error` event "translation model unavailable").

- [ ] **Step 4: Wire.** `Sidekick.__init__`: `self.models = ModelManager(self.llm, cfg, self.events)`; `Sidekick.start()` calls `threading.Thread(target=self.models.start, daemon=True)` instead of `llm.warm`; `ModeManager.set_mode` runs `await loop.run_in_executor(None, self.models.enter, mode)` for `interpreter` (publish earcon `mode_on` and phrase "Starting interpreter" *before* awaiting) and `leave` when exiting it. `ModeManager` takes `models=None` (optional, default no-op) so existing tests keep working.

- [ ] **Step 5: Suite. Commit** `feat: model residency manager`.

---

### Task 7: ButtonMapGuard

**Files:**
- Create: `assistant/buds_assistant/buttonmap.py`
- Modify: `assistant/buds_assistant/sidekick.py`, `assistant/buds_assistant/config.py` (`hold_remap: str = "other_l"` is wrong for right side; use `hold_remap_left: str = "other_l"`, `hold_remap_right: str = "other_r"`)
- Test: `assistant/tests/test_buttonmap.py`

**Interfaces:**
- Produces: `ButtonMapGuard(path: Path, send: Callable[[str, str], Awaitable[None]], events)`; `async apply(current_left: str, current_right: str, target_left: str, target_right: str)`; `async restore()`; `async recover()`; saved file `data_dir/buttonmap.json` `{"left":..., "right":...}` written atomically (write temp + `os.replace`) BEFORE sending the remap. `send(left, right)` sends the allowlisted `touchpad_option` command.

- [ ] **Step 1: Failing tests**

```python
import json

from buds_assistant.buttonmap import ButtonMapGuard
from buds_assistant.events import EventBus


async def test_apply_saves_original_before_sending(tmp_path):
    sent = []
    async def send(l, r):
        assert json.loads((tmp_path / "buttonmap.json").read_text()) == {"left": "noise_control", "right": "noise_control"}
        sent.append((l, r))
    g = ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus())
    await g.apply("noise_control", "noise_control", "other_l", "other_r")
    assert sent == [("other_l", "other_r")]


async def test_second_apply_never_overwrites_the_saved_original(tmp_path):
    async def send(l, r): pass
    g = ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus())
    await g.apply("noise_control", "noise_control", "other_l", "other_r")
    await g.apply("other_l", "other_r", "other_l", "other_r")          # we now read OUR remap back from the buds
    assert json.loads((tmp_path / "buttonmap.json").read_text())["left"] == "noise_control"


async def test_restore_sends_original_and_clears_file(tmp_path):
    sent = []
    async def send(l, r): sent.append((l, r))
    g = ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus())
    await g.apply("volume", "spotify", "other_l", "other_r")
    await g.restore()
    assert sent[-1] == ("volume", "spotify") and not (tmp_path / "buttonmap.json").exists()


async def test_recover_after_crash_restores_on_next_start(tmp_path):
    (tmp_path / "buttonmap.json").write_text(json.dumps({"left": "noise_control", "right": "volume"}))
    sent = []
    async def send(l, r): sent.append((l, r))
    await ButtonMapGuard(tmp_path / "buttonmap.json", send, EventBus()).recover()
    assert sent == [("noise_control", "volume")] and not (tmp_path / "buttonmap.json").exists()


async def test_send_failure_is_reported_not_raised(tmp_path):
    async def send(l, r): raise RuntimeError("buds gone")
    ev = EventBus()
    await ButtonMapGuard(tmp_path / "buttonmap.json", send, ev).apply("volume", "volume", "other_l", "other_r")
    assert ev.recent(types={"error"})
```

- [ ] **Step 2: FAIL. Step 3: Implement**

```python
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
```

- [ ] **Step 4: Wire into `Sidekick`.** `_send_touch(l, r)` builds `C.build("touchpad_option", {"left": l, "right": r}, state)`, `C.check_tx_id`, sends (same pattern as `_ambient`). In `_start_link` after the link is up: `await self.buttons.recover()`; when the first state snapshot containing `touch_option_l` arrives (`on_event` for `battery`/`wear` events, once), call `buttons.apply(st["touch_option_l"], st["touch_option_r"], cfg.hold_remap_left, cfg.hold_remap_right)`. In `stop()`: `await self.buttons.restore()` before closing the link. `--simulate` skips all of this.

- [ ] **Step 5: Suite. Commit** `feat: button map guard with crash recovery`.

---

### Task 8: UiState (push-based state)

**Files:**
- Create: `assistant/buds_assistant/uistate.py`
- Modify: `assistant/buds_assistant/sidekick.py` (construct, expose), `assistant/buds_assistant/dashboard/server.py` (`/ws` sends snapshot on connect, `/api/v2/state` returns it)
- Test: `assistant/tests/test_uistate.py`

**Interfaces:**
- Produces: `UiState(events)`; `.snapshot() -> dict` with keys `mode, memory_level, placement, buds {battery, wear}, models, autopilot {sensitivity, enabled, feed}, banner`; it subscribes to the bus and republishes a full `ui_state` event after every change from event types `mode, battery, wear, model_state, autopilot_decision, buds`. `autopilot.feed` is the last 30 decisions.

- [ ] **Step 1: Failing tests**

```python
from buds_assistant.events import EventBus
from buds_assistant.uistate import UiState


def test_reduces_events_into_one_snapshot_and_pushes_it():
    ev = EventBus(); ui = UiState(ev)
    ev.publish("mode", mode="listen", placement="ear", memory_level="remember", autopilot=False, route="ear",
               conversation_id=3, ring_seconds=2.0)
    ev.publish("battery", left=80, right=79, case=50)
    ev.publish("model_state", chat="ready", embed="ready", translate="unloaded")
    s = ui.snapshot()
    assert s["mode"] == "listen" and s["buds"]["battery"]["left"] == 80 and s["models"]["chat"] == "ready"
    assert ev.recent(types={"ui_state"})[-1]["data"]["mode"] == "listen"


def test_feed_keeps_last_30_decisions():
    ev = EventBus(); ui = UiState(ev)
    for i in range(40):
        ev.publish("autopilot_decision", outcome="held_back", reason="too_soon", text=f"h{i}")
    feed = ui.snapshot()["autopilot"]["feed"]
    assert len(feed) == 30 and feed[-1]["text"] == "h39"


def test_buds_disconnect_sets_banner():
    ev = EventBus(); ui = UiState(ev)
    ev.publish("buds", message="not connected")
    assert ui.snapshot()["banner"]
```

- [ ] **Step 2: FAIL. Step 3: Implement** a reducer dict keyed by event type; guard against re-entrancy (don't react to its own `ui_state` events); `buds` events whose message contains "not connected", "error" or "timed out" set `banner = "Buds not connected. Pause: ..."` and `link up` events clear it (look for the message wording the bridge emits in `bridge.py` and match on those strings; add a test line for the clear case).

- [ ] **Step 4: Dashboard.** Read the `/ws` handler in `dashboard/server.py` (line ~276). On connect, send `{"type":"ui_state","data": sk.ui.snapshot()}` first; add `GET /api/v2/state`. Add a `TestClient` test: connecting to `/ws` first message has type `ui_state`.

- [ ] **Step 5: Suite. Commit** `feat: push-based UiState snapshot`.

---

### Task 9: Decision log, commitment detector, AutopilotEngine

**Files:**
- Modify: `assistant/buds_assistant/store.py` (new table + 2 methods), `assistant/buds_assistant/config.py` (`autopilot_sensitivity`, `autopilot_categories`), `assistant/buds_assistant/policy.py` (shim)
- Create: `assistant/buds_assistant/commitments.py`, `assistant/buds_assistant/autopilot.py`
- Test: `assistant/tests/test_commitments.py`, `assistant/tests/test_autopilot.py`; existing `tests/test_policy.py` and `tests/test_pipeline_policy.py` must still pass untouched.

**Interfaces:**
- Produces:
  - `store.log_decision(trigger: str, outcome: str, reason: str | None, text: str, person_id: int | None, conv_id: int | None, hint_id: int | None) -> int`, `store.decisions(limit: int = 100) -> list[dict]`. Table `autopilot_decisions(id, ts, conv_id, trigger, outcome, reason, text, person_id, hint_id)`. `outcome` in `said | noted | held_back`.
  - `commitments.Commitment(text: str, due: str | None)`; `commitments.detect(text: str) -> Commitment | None`.
  - `AutopilotEngine(cfg, store, memory, events=None)` with the same `on_segment(e, now)`, `feedback(...)`, `enabled` as v1 `Policy`; `Hint` gains `kind: str = "said"` (`"noted"` for capture) and `ts: float`; triggers: `capture` (A3), `question` (A2), `identity` (A1), `commitment` (A4), `mention` (A5). `.sensitivity` property reads `cfg.autopilot_sensitivity`.
  - Held-back reasons (exact strings): `autopilot_off`, `too_soon`, `hourly_budget`, `recently_dismissed`, `category_off`, `unknown_voice`, `you_were_speaking` (set by delivery, Task 10), `stale` (Task 10), `no_confident_match`.

- [ ] **Step 1: Failing tests for the detector**

```python
import pytest

from buds_assistant.commitments import detect


@pytest.mark.parametrize("text,expected_text,expected_due", [
    ("I'll send it Friday", "send it", "Friday"),
    ("I will call Anita tomorrow morning", "call Anita", "tomorrow"),
    ("Let me email the contract by Monday", "email the contract", "Monday"),
    ("I'm going to review the slides tonight", "review the slides", "tonight"),
    ("I will send you the report by Friday afternoon", "send you the report", "Friday"),
])
def test_detects_first_person_promises(text, expected_text, expected_due):
    c = detect(text)
    assert c and c.text == expected_text and c.due == expected_due


@pytest.mark.parametrize("text", ["I will be there on time", "I'll think about it", "He will send it Friday",
                                  "Did you send the report?", "I sent it yesterday", "we could maybe call"])
def test_ignores_non_commitments(text):
    assert detect(text) is None
```

- [ ] **Step 2: FAIL. Step 3: Implement `commitments.py`**

```python
"""Rule-based commitment capture (A3): first-person promise + action verb, optional due phrase. No model, no history needed."""
from __future__ import annotations

import re
from dataclasses import dataclass

VERBS = "send|call|email|share|review|finish|finali[sz]e|check|schedule|book|prepare|update|follow up|bring|submit|forward|ping|text"
DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tonight|tomorrow"
PROMISE = re.compile(rf"\b(?:i(?:'ll| will| am going to|'m going to)|let me)\s+((?:{VERBS})\b[^,.?!]*)", re.I)
DUE = re.compile(rf"\b(?:by|on|before|this|next|until)?\s*\b({DAYS}|end of (?:the )?(?:day|week|month)|next week)\b", re.I)


@dataclass
class Commitment:
    text: str
    due: str | None


def detect(text: str) -> Commitment | None:
    m = PROMISE.search(text)
    if not m:
        return None
    body = m.group(1).strip()
    due = None
    d = DUE.search(body)
    if d:
        due = d.group(1)
        due = due[0].upper() + due[1:] if due.lower() in DAYS.split("|") else due
        body = (body[:d.start()] + body[d.end():]).strip()
        body = re.sub(r"\s+(?:by|on|before|this|next|until)$", "", body, flags=re.I).strip()
        body = re.sub(r"\s+(?:morning|afternoon|evening)$", "", body, flags=re.I).strip()
    return Commitment(body, due)
```

Run the parametrized cases; adjust the regexes until all 11 pass (the trailing "morning/afternoon" and the `by`/`on` stripping are the usual snags). Do not loosen `VERBS` to make a failing negative pass.

- [ ] **Step 4: Failing tests for the engine** (`tests/test_autopilot.py`), using `seed()` and `ev()` copied from `tests/test_policy.py` (import them: `from test_policy import seed, ev`):

```python
from buds_assistant.autopilot import AutopilotEngine


def decisions(s):
    return [(d["trigger"], d["outcome"], d["reason"]) for d in s.decisions()]


def test_capture_works_on_cold_start(tmp_path):
    from buds_assistant.config import Config
    from buds_assistant.llm import FakeLLM
    from buds_assistant.memory import Memory
    from buds_assistant.store import Store
    s = Store(tmp_path); me = s.add_person("Me")
    p = AutopilotEngine(Config(data_dir=tmp_path), s, Memory(s, FakeLLM())); p.enabled = True
    h = p.on_segment(ev(me, "Me", "I'll send it Friday", is_self=True), 1000.0)
    assert h and h.kind == "noted" and h.trigger == "capture" and "send it" in h.text and "Friday" in h.text
    assert s.facts(person_id=me, kind="commitment")[0]["text"] == "send it"
    assert decisions(s)[-1][:2] == ("capture", "noted")


def test_every_suppressed_candidate_has_a_reason(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.enabled = False
    p.on_segment(ev(ravi, "Ravi", "Hello there"), 1000.0)
    assert ("identity", "held_back", "autopilot_off") in decisions(s)
    p.enabled = True
    p.on_segment(ev(ravi, "Ravi", "Hello again"), 1001.0)                 # identity said
    p.on_segment(ev(ravi, "Ravi", "When is the Q3 report due?"), 1005.0) # question, 4 s later
    assert any(d[1:] == ("held_back", "too_soon") for d in decisions(s))


def test_unknown_voice_question_is_logged_not_whispered(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    assert p.on_segment(ev(None, "Speaker A", "When is the demo?"), 1000.0) is None
    assert ("question", "held_back", "unknown_voice") in decisions(s)


def test_quiet_sensitivity_only_capture_and_question(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    cfg.autopilot_sensitivity = "quiet"
    assert p.on_segment(ev(ravi, "Ravi", "Good morning"), 1000.0) is None
    assert ("identity", "held_back", "category_off") in decisions(s)


def test_category_override(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    cfg.autopilot_categories = ["identity"]
    assert p.on_segment(ev(ravi, "Ravi", "Good morning"), 1000.0).trigger == "identity"


def test_capture_is_not_blocked_by_min_gap_but_counts_to_budget(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    p.on_segment(ev(ravi, "Ravi", "Good morning"), 1000.0)
    h = p.on_segment(ev(me, "Me", "I will call Anita tomorrow", is_self=True), 1002.0)
    assert h and h.trigger == "capture"


def test_mention_of_known_person_gives_brief(tmp_path):
    p, s, ravi, me, cfg = seed(tmp_path)
    s.add_fact(ravi, "fact", "is the new finance lead", None, None)
    h = p.on_segment(ev(me, "Me", "Is Ravi coming?", is_self=True), 1000.0)    # self speech mentioning Ravi
    assert h and h.trigger == "mention" and "finance lead" in h.text
```

Also keep v1 behaviour: wearer speech sets `user_last` (so hints are held while you just spoke): a test `test_no_hint_right_after_you_spoke` asserting reason `you_were_speaking`... that reason belongs to delivery; here the engine's own `now - user_last > 1.5` check logs `too_soon`. Use that.

- [ ] **Step 5: FAIL. Step 6: Implement.**
  - `store.py`: add to `SCHEMA` `CREATE TABLE IF NOT EXISTS autopilot_decisions(id INTEGER PRIMARY KEY, ts REAL, conv_id INTEGER, trigger TEXT, outcome TEXT, reason TEXT, text TEXT, person_id INTEGER, hint_id INTEGER);` and the two methods mirroring `log_hint`/`hints`.
  - `config.py`: `autopilot_sensitivity: str = "balanced"`, `autopilot_categories: list | None = None`.
  - `autopilot.py`: move `Hint`, `clip_words`, `QUESTION` and the class from `policy.py`, rename to `AutopilotEngine`, constructor `(cfg, store, memory, events=None)` (store `self.conv_id = None`, set by the pipeline). Add:
    - `SENS = {"quiet": {"capture","question"}, "balanced": {"capture","question","identity","commitment","mention"}, "proactive": {"capture","question","identity","commitment","mention"}}`; `_enabled_categories()` returns `cfg.autopilot_categories` if set else `SENS[...]`.
    - `_gate(trigger, now, bypass_gap=False) -> str | None` returning a reason string from the list above, else `None`; replaces `_allowed`.
    - `_decide(trigger, outcome, reason, text, pid, hint_id=None)` writes `store.log_decision(...)` and publishes `autopilot_decision` (`events` may be `None`).
    - `on_segment`: self speech → (A3) `detect()`; on a hit and category enabled and `enabled`: persist fact via `store.add_fact(pid, "commitment", c.text, c.due, e.get("seg_id"), owner="Me")` when the Me person row exists and its policy is not `none`, build `Hint(f"Noted: {c.text}" + (f", {c.due}" if c.due else ""), "capture", pid, kind="noted")` with the fact id on `hint.fact_id`, `_emit`, log `noted`. Self speech mentioning a known person's name (A5) → `mention` brief from that person's facts (`kind != "commitment"` first fact, <=12 words). Non-self known voice → existing identity / commitment / question logic, each wrapped with `_gate` + `_decide`. Unknown voice with `QUESTION` match → `held_back unknown_voice`. Questions with no hit above 0.35 → `held_back no_confident_match`.
    - `feedback`: unchanged, plus `_decide` is not called; add `muted` reason `recently_dismissed` via `_gate`.
  - `policy.py` becomes: `from .autopilot import AutopilotEngine as Policy, Hint, clip_words, QUESTION  # noqa: F401`.
  - Pipeline: `ConversationPipeline.start` sets `self.policy.conv_id = self.conv_id` when the policy has that attribute.

- [ ] **Step 7: Run `tests/test_commitments.py tests/test_autopilot.py tests/test_policy.py tests/test_pipeline_policy.py`.** Expected: all PASS. Then the full suite.

- [ ] **Step 8: Commit** `feat: AutopilotEngine with decision log, commitment capture, sensitivity`.

---

### Task 10: Delivery, handlers and the speaking guard

**Files:**
- Modify: `assistant/buds_assistant/segmenter.py` (`speaking` property), `assistant/buds_assistant/pipeline.py` (`user_speaking()`), `assistant/buds_assistant/sidekick.py` (`_on_hint` → `_deliver`, handlers)
- Test: `assistant/tests/test_autopilot_delivery.py`

**Interfaces:**
- Consumes: `GestureContext.open` (Task 3), `OutputArbiter.earcon` (Task 5), `AutopilotEngine` (Task 9), `Store.set_fact_status`.
- Produces: `Segmenter.speaking -> bool` (true while a segment is open), `ConversationPipeline.user_speaking() -> bool`, `Sidekick._deliver(hint) -> None` (async), `Sidekick.last_hint`, handlers `tell_more`, `not_useful`, `undo_commitment`.

Delivery rules: stale if `now - hint.ts > cfg.hint_ttl` → log `held_back stale`; if `pipeline.user_speaking()` poll every 100 ms until a gap, up to the remaining ttl, else log `held_back you_were_speaking`; on delivery play earcon `whisper` (or `noted` for `kind == "noted"`), then `output.say(text, "en", "hint", whisper=True)`, then `context.open("noted" if noted else "whisper", time.monotonic())`.
Handlers: `tell_more` → say the source line (`store.segments` row for `hint.sources[0]`, "From <weekday>: <text>") or "No more detail."; `not_useful` → `policy.feedback(last_hint.id, False, last_hint.trigger)` + earcon `accepted`; `undo_commitment` → `store.set_fact_status(hint.fact_id, "cancelled")`, say "Undone", earcon `mode_off`.

- [ ] **Step 1: Failing tests** (build the Sidekick exactly like `tests/test_dashboard.py::_make`; use `FakePlayer`s and `Config(data_dir=tmp_path, hint_ttl=0.5)`):

```python
import asyncio, time
from buds_assistant.autopilot import Hint


async def test_hint_is_spoken_and_opens_whisper_window(sk):
    h = Hint("Ravi. He owes you the Q3 report.", "identity", 1, ts=time.time()); h.id = 1
    await sk._deliver(h)
    assert any(x["kind"] == "speak" and x["priority"] == "hint" for x in sk.output.log)
    assert sk.modes.context.intercept("L:single", time.monotonic(), speaking=False) == "tell_more"


async def test_stale_hint_is_dropped_with_reason(sk):
    h = Hint("old", "identity", 1, ts=time.time() - 10); h.id = None
    await sk._deliver(h)
    assert ("identity", "held_back", "stale") in [(d["trigger"], d["outcome"], d["reason"]) for d in sk.store.decisions()]
    assert not any(x["kind"] == "speak" for x in sk.output.log)


async def test_hint_waits_while_wearer_speaks_then_drops(sk):
    sk.pipeline.user_speaking = lambda: True
    h = Hint("late", "identity", 1, ts=time.time())
    await sk._deliver(h)
    assert ("identity", "held_back", "you_were_speaking") in [(d["trigger"], d["outcome"], d["reason"]) for d in sk.store.decisions()]


async def test_not_useful_mutes_that_trigger(sk):
    h = Hint("x", "identity", 1, ts=time.time()); h.id = sk.store.log_hint("identity", "x", 1, True)
    sk.last_hint = h
    await sk._handlers()["not_useful"]()
    assert sk.policy.muted["identity"] > time.time() - 1


async def test_undo_commitment_cancels_fact(sk):
    me = sk.store.add_person("Me"); fid = sk.store.add_fact(me, "commitment", "send it", "Friday", None, owner="Me")
    h = Hint("Noted: send it, Friday", "capture", me, kind="noted", ts=time.time()); h.fact_id = fid
    sk.last_hint = h
    await sk._handlers()["undo_commitment"]()
    assert sk.store.facts(person_id=me, kind="commitment", status="open") == []
```

`sk` fixture: `Sidekick` via the `_make` helper from `test_dashboard.py` (import it), plus `await sk.start()` is not needed.

- [ ] **Step 2: FAIL. Step 3: Implement** the rules above. `Hint` already has `ts` (Task 9); `Hint.fact_id: int | None = None` is added there. Keep `Sidekick._on_hint(hint)` as the thread-safe bridge: `asyncio.run_coroutine_threadsafe(self._deliver(hint), self.loop)`. In `_deliver`, log held-back via `self.store.log_decision(...)` and `self.events.publish("autopilot_decision", ...)`.

- [ ] **Step 4: Suite. Commit** `feat: whisper delivery with stale/speaking guards and feedback gestures`.

---

### Task 11: Scripted conversation gate (precision, cold start, rate)

**Files:**
- Create: `assistant/tests/fixtures_autopilot.py`, `assistant/tests/test_autopilot_script.py`

**Interfaces:**
- Consumes: `AutopilotEngine`, `Store`, `Memory(FakeLLM)`.
- Produces: `SCRIPT: list[Line]` where `Line = (offset_seconds, speaker, person_key, text, is_self, expected_trigger | None)`, covering about 10 minutes (offsets 0..600) with 3 people (Me, Ravi, Priya) and these labelled points: Ravi first turn (`identity`), Priya asks "When is the demo?" (`question`, only when memory has it), Me says "I'll send the deck Friday" (`capture`), Ravi mentions the budget while an open commitment exists (`commitment`), and about 8 filler lines with `None`.

- [ ] **Step 1: Write the fixture** with real lines and labels (no placeholders; at least 24 lines). Include one question from an unknown voice (`expected None`), and two Me lines that are chatter (`None`).

- [ ] **Step 2: Write the tests**

```python
def run(script, engine, people):
    said = []
    for off, name, key, text, is_self, expected in script:
        e = {"person_id": people.get(key), "speaker": name, "text": text, "is_self": is_self, "seg_id": None}
        h = engine.on_segment(e, 1000.0 + off)
        if h:
            said.append((off, h.trigger, expected))
    return said


def test_precision_at_least_70_percent_with_memory(tmp_path): ...
def test_cold_start_still_captures_commitments(tmp_path): ...     # only "Me" enrolled, no facts; >= 1 capture, all captures labelled
def test_rate_never_exceeds_config(tmp_path): ...                  # <= hints_per_hour and gaps >= hint_min_gap except captures
def test_no_whisper_for_unknown_voices(tmp_path): ...
```

Fill each body fully (precision = hits where `trigger == expected` divided by total whispers; assert `>= 0.7`; cold start asserts `any(t == "capture")`; rate asserts `len(said) <= cfg.hints_per_hour` and consecutive non-capture whispers are `>= cfg.hint_min_gap` apart; unknown assertion checks the labelled unknown-voice line produced no whisper).

- [ ] **Step 3: Run; fix the engine (not the labels) until green.** If precision < 70 % because a trigger is too eager, tighten the trigger and add a regression test for that false positive.

- [ ] **Step 4: Commit** `test: scripted autopilot conversation gate`.

---

### Task 12: Wrap-up, docs, hardware checklist

**Files:**
- Modify: `assistant/README.md`, `docs/specs/spec-v2.md` (status), `docs/validation/phase0-v2.md`
- Create: `docs/hardware-checklist-v2.md`

- [ ] **Step 1: Full suite** `../.venv/bin/python -m pytest -m "not slow" -q`. Paste the final pass count into `docs/validation/phase0-v2.md`.
- [ ] **Step 2: Simulator run** `../.venv/bin/python -m buds_assistant.sidekick --simulate --silent`; in a second shell use the dashboard gesture simulator (or `curl` the gesture endpoint) to send `R:hold_start` (listen), `R:double` (autopilot), then feed a segment through the existing demo (`buds_assistant.demo`) and confirm in the event log: `mode` events, `autopilot_decision` events, and `ui_state` pushes. Record what was seen in `docs/validation/phase0-v2.md`.
- [ ] **Step 3: `docs/hardware-checklist-v2.md`**: each gesture in both placements, anti-accident (insert/remove a bud, pocket shake), button map applied and restored (also after `kill -9`), earcons audible and distinct, Autopilot whisper heard in a real 10-minute conversation with a friend, 👍/👎 by double/single tap, interpreter-mode entry pauses autopilot, model readiness after cold start.
- [ ] **Step 4: README**: replace the mode and gesture tables with the v2 ones; document `autopilot_sensitivity` and the decision log (`store.decisions()`).
- [ ] **Step 5: Commit** `docs: v2 phases 0-2 wrap-up`.

---

# Phase 3: Dashboard v2

**Design bar (spec 8, principles):** opens to a calm Home showing what Sidekick is doing right now; plain language only (no cluster/embedding/STT/JSON); every empty state says what to do next; every error says what is wrong and offers the fix; no `alert/confirm` (in-page dialogs with undo); light and dark themes; keyboard shortcuts; laptop and tablet width; state is pushed over the WebSocket (no polling). Load the `frontend-design` skill before Task 14 and follow its guidance for visual identity (one distinctive, calm direction, real type scale, no templated defaults).

**Global frontend rules**
- One reactive store (`web/js/store.js`): holds the last `ui_state` snapshot plus append-only lists (`segments`, `hints/decisions`, `toasts`); components subscribe; the backend owns the truth. Reconnect with backoff; a visible "Reconnecting" banner.
- API under `/api/v2/*`, versioned; old `/api/*` stays for the Developer view.
- Vendored runtime: `web/vendor/htm-preact-standalone.module.js` (htm/preact standalone bundle, downloaded once with `curl` from jsdelivr, committed). No CDN at runtime.
- Files: `web/index.html` (shell), `web/css/{tokens,base,components}.css`, `web/js/{main,store,api,router}.js`, `web/js/components/*.js`, `web/js/views/{home,live,people,library,settings,onboarding,developer}.js`. The v1 dashboard moves to `web/dev/` and is served at `/dev` (Developer view link in Settings > Advanced).
- Every view must render from a fixture snapshot with no backend (`web/js/fixtures.js`, used in `?demo=1`), so design review and the browser checks do not need models running.

### Task 13: Backend API v2

**Files:**
- Create: `assistant/buds_assistant/dashboard/api_v2.py` (router, mounted by `create_app`)
- Modify: `assistant/buds_assistant/dashboard/server.py` (mount router, move static to `web/`, serve old UI from `web/dev/`), `assistant/buds_assistant/sidekick.py` (`gesture_catalog()`, `health()`)
- Test: `assistant/tests/test_api_v2.py`

**Interfaces (all JSON):**
- `GET /api/v2/state` -> `UiState.snapshot()` (Task 8).
- `POST /api/v2/mode` `{mode}` -> snapshot; `POST /api/v2/memory-level` `{level}` -> snapshot (400 with plain message for invalid combo, e.g. recording in standby: `"Recording needs Listen, Autopilot or Interpreter to be on."`).
- `GET/PUT /api/v2/autopilot` `{sensitivity: "quiet|balanced|proactive", categories: {identity, question, capture, commitment, mention}: bool}` (PUT writes `cfg.autopilot_sensitivity` / `cfg.autopilot_categories`, audits).
- `GET /api/v2/autopilot/feed?n=50` -> last decisions, each `{id, ts, trigger, outcome, reason, reason_text, text, person, hint_id}`; `reason_text` is the plain-language string (map: `too_soon` "Skipped: too soon after the last whisper", `you_were_speaking` "Held back: you were speaking", `stale` "Dropped: the moment had passed", `unknown_voice` "Skipped: I don't know this voice", `category_off` "Skipped: this type of hint is switched off", `autopilot_off` "Autopilot was off", `hourly_budget` "Skipped: hourly limit reached", `recently_dismissed` "Skipped: you dismissed this kind recently", `no_confident_match` "Skipped: no confident answer").
- `POST /api/v2/hints/{id}/feedback` `{useful}`; `POST /api/v2/commitments/{fact_id}/undo`.
- `GET /api/v2/health` -> `{checks: [{id, label, ok, detail, fix}]}` for: `ollama` (running), `models` (chat, embed, translate present via `/api/tags`), `buds` (link up), `speaker_model` (file exists), `whisper` (importable). `fix` is a plain sentence, e.g. "Start Ollama with `ollama serve`".
- `GET /api/v2/unnamed` -> clusters from today `[{label, utterances, last_text, seconds}]`; `POST /api/v2/unnamed/{label}/name` `{name, consent}`.
- `GET/PUT /api/v2/gestures` -> `{profiles: {ear: [...], remote: [...]}, actions: [{id, label}]}`; PUT `{bindings: [{gesture, action}]}` validates each `action` against `ACTIONS`, rejects duplicate gestures, writes `sidekick_gestures.yaml` (backup to `.bak` first) and hot-reloads recognizers (`mode_manager.reload_profiles()`); `POST /api/v2/gestures/reset` restores the shipped default.
- `GET /api/v2/people/{id}` -> person page `{person, facts, commitments, recent_conversations, brief}`; `DELETE /api/v2/people/{id}` is a two-step: `POST /forget-preview` returns counts, `POST /forget` executes (the UI shows the counts in an in-page dialog).
- `GET /api/v2/library?q=` -> conversation cards `{id, title, date, people, summary, marks}`; `GET /api/v2/library/{id}` -> card + transcript + bookmarks; `GET /api/v2/open-loops` -> commitments across people with due dates, owner, status; `POST /api/v2/open-loops/{id}/done`.

- [ ] **Step 1: Failing tests** in `tests/test_api_v2.py` using the `_make` helper from `test_dashboard.py` and `TestClient`. Cover: state shape; invalid memory level message; autopilot PUT changes `cfg` and audits; feed includes `reason_text` for a seeded `held_back too_soon`; health returns one check per id with `fix` when failing (FakeLLM `up=False` -> `ollama.ok False` and a fix string); gestures PUT rejects an unknown action and a duplicate gesture and writes a `.bak`; gestures reset restores defaults; unnamed list and naming round trip with consent required (400 without consent); forget-preview counts match `forget` counts; open-loops `done` flips status; library search returns a card for a seeded conversation.
- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement** `api_v2.py` as an `APIRouter` built by `make_router(sk)`; reuse `sk.store`, `sk.memory`, `sk.speaker`, `sk.pipeline`. `ModeManager.reload_profiles(path)` rebuilds `recognizers` from `load_profiles`. `ACTIONS` is a module constant in `modes.py` listing every dispatchable action with a plain label (used by the editor dropdowns).
- [ ] **Step 4: Move the old UI.** `git mv assistant/buds_assistant/dashboard/web assistant/buds_assistant/dashboard/web_v1` then create `web/` for v2 and `shutil.copytree`-free approach: mount `/dev` -> `web_v1`, `/` -> `web`. Update `test_dashboard.py` index test to hit `/dev/`.
- [ ] **Step 5: Suite. Commit** `feat: dashboard v2 API`.

### Task 14: Frontend foundation, design system, shell

**Files:** Create `web/index.html`, `web/css/tokens.css`, `web/css/base.css`, `web/css/components.css`, `web/js/{main,store,api,router,fixtures}.js`, `web/js/components/{StatusPill,Card,Button,Dialog,Toast,EmptyState,Icon}.js`, `web/vendor/htm-preact-standalone.module.js`.

- [ ] **Step 1:** `curl -L https://cdn.jsdelivr.net/npm/htm@3/preact/standalone.module.js -o web/vendor/htm-preact-standalone.module.js`; confirm it exports `html, render, useState, useEffect, useMemo, useRef` (open it, grep `export`); commit with its version noted in `web/vendor/README.md`.
- [ ] **Step 2: Design tokens** (`tokens.css`): colour roles (surface, surface-raised, ink, ink-muted, accent, listening, autopilot, interpreter, private, warn, ok), a modular type scale, spacing scale, radius, motion (150 ms ease, `prefers-reduced-motion` respected), light + dark via `prefers-color-scheme` plus `[data-theme]` override, 16 px gutters, no horizontal scroll at 360 px. Mode colours are distinct and colour is never the only signal (icon + label).
- [ ] **Step 3: Store + API client.** `store.js`: `connect()` opens `/ws`, applies `ui_state` and domain events (`segment`, `autopilot_decision`, `hint`, `reply`, `toast`), exposes `useStore(selector)`; reconnect with 0.5/1/2/5 s backoff and `connection` state. `api.js`: `get/post/put` helpers returning parsed JSON and throwing `Error(message)` with the server's plain message. Test (browser, Step 6).
- [ ] **Step 4: Shell + router.** Hash router: `#/home`, `#/live`, `#/people`, `#/people/:id`, `#/library`, `#/library/:id`, `#/settings`, `#/setup`, `#/dev`. Top bar: Sidekick wordmark, current-mode chip (always visible), buds pill (battery, in ear / out), banner slot (connection, buds not connected, Ollama down). Left rail (icons + labels) collapses to a bottom tab bar under 720 px. Keyboard: `g h/l/p/b/s` navigation, `?` shortcut sheet, `Esc` closes dialogs. First run (no enrolled "You") redirects to `#/setup`.
- [ ] **Step 5: Components** with props and states documented in a comment each: Dialog (focus trap, undo-capable footer), Toast (with Undo action, 6 s), EmptyState (icon, one sentence, one primary action), Card, Button (variants: primary, quiet, danger).
- [ ] **Step 6: Verify in the browser.** Start `python -m buds_assistant.sidekick --simulate --silent`, open `http://127.0.0.1:8770/?demo=1` with Claude-in-Chrome, screenshot light and dark at 1280 px and 390 px width, confirm no console errors (`read_console_messages`), keyboard nav works. Save screenshots to `docs/design/screenshots/` and note what was seen.
- [ ] **Step 7: Commit** `feat: dashboard v2 foundation and design system`.

### Task 15: Home and Live conversation

**Files:** Create `web/js/views/home.js`, `web/js/views/live.js`, `web/js/components/{ModeCard,WhosHere,TranscriptBubble,AutopilotFeed,AskBar,ActionBar}.js`; Test: `tests/test_api_v2.py` additions for any new endpoint.

Home contents (spec 8.3): big status card in plain words (`Standby, ready`, `Listening`, `Autopilot on`, `Interpreting`, `Private`, with one supporting line, e.g. "3 people here, last whisper 2 min ago"); four mode cards (Listen, Autopilot, Interpreter, Private) each with one-line description and an on/off control; memory-level control (Live only / Remember / Recording with the first-use consent notice dialog); buds pills; permanent Ask bar (type, or press-and-hold mic button = dashboard capture). When a conversation is active, Home embeds the Live panel.

Live panel: **Who's here** strip (avatar per voice, pulse on the current speaker, confidence ring, grey "unsure" instead of a wrong name, one-tap "Is this Priya?" suggestion slot reserved for Phase 6); transcript as chat bubbles with names and colours, Telugu flagged "experimental"; "noticed so far" side panel (commitments, marks); **Autopilot feed** (spec 5.8) with three entry kinds: Said (👍/👎), Noted (Undo), Held back (reason_text, muted style); big buttons Replay, Mark, Catch me up, Recording on/off, Private.

- [ ] **Step 1:** Fixtures for every state (standby, listen with 3 speakers, autopilot with feed of each entry kind, interpreter, private, buds disconnected, Ollama down).
- [ ] **Step 2:** Build components against fixtures; mode switching calls `POST /api/v2/mode` with optimistic UI that rolls back with a toast on error; click-to-visible-response under 100 ms (optimistic).
- [ ] **Step 3:** Wire the live store events; the transcript auto-scrolls unless the user scrolled up ("Jump to latest" chip).
- [ ] **Step 4: Verify in the browser** with the simulator: run `POST /api/simulate/conversation`, record a GIF (`gif_creator`) of Standby -> Listen -> Autopilot with the feed filling, save to `docs/design/screenshots/home-live.gif`; screenshots of each state in light/dark.
- [ ] **Step 5: Commit** `feat: dashboard v2 Home and Live conversation`.

### Task 16: People and Library

**Files:** Create `web/js/views/{people,person,library,conversation}.js`, `web/js/components/{PersonCard,UnnamedTray,ConfirmDialog,ConversationCard,ActionItem,SearchBar}.js`.

People: cards (avatar, last talked, open commitments, key facts); **Unnamed voices tray** (today's clusters with Listen (plays the stored in-RAM clip) and Name -> consent dialog in plain words); add voice sample; remember setting as plain choices ("Notes only", "Notes and audio", "Don't remember"); **Forget** opens the in-page dialog showing exact counts from `forget-preview` ("This deletes 12 notes, 2 recordings, 1 voiceprint. This cannot be undone.") with typed confirmation of the person's name. Person page: facts, topics, last conversations, open commitments, "before you talk to Ravi" brief.
Library: conversation cards (title, date, people, one-line summary); opening shows the card (summary, action items to tick off, transcript with marks highlighted, recording if any); search bar ("what did people say about..."); **Open loops** tab (yours and theirs, due dates, tick to complete, Undo toast).

- [ ] **Step 1:** Fixtures + empty states ("No one saved yet. Enrol yourself first. [Start setup]").
- [ ] **Step 2:** Build views; destructive actions use `ConfirmDialog` and offer Undo where reversible (tick-off, rename, policy change); Forget is irreversible and says so.
- [ ] **Step 3:** Verify in the browser against a seeded store (`POST /api/people/demo`, simulate conversation, extract facts) and with `?demo=1`; screenshots light/dark, narrow width; record findings.
- [ ] **Step 4: Commit** `feat: dashboard v2 People and Library`.

### Task 17: Settings and gesture editor

**Files:** Create `web/js/views/settings.js`, `web/js/components/{GestureEditor,Segmented,Toggle,Slider}.js`.

Settings groups (plain language): **Autopilot** (sensitivity segmented Quiet/Balanced/Proactive with one-line behaviour text; per-category checkboxes: "Tell me who is speaking", "Answer questions I can answer from memory", "Note my promises", "Remind me of promises", "Brief me when a name comes up"); **Gestures** (diagram of two buds with 4 gestures each, a dropdown per slot, **Try it** mode that highlights the live detected gesture (from `token` events) and shows what it would do without doing it, Reset to defaults); **Voice commands** (wake phrase field, disabled with "Coming soon" until Phase 4); **Languages** (English, Telugu on/off with the "experimental" note, translation quality note); **Devices & audio** (capture source per mode, replay length slider 5 to 60 s, volumes); **Privacy & data** (defaults for remembering/recording/retention, activity log in readable sentences with export, "Delete everything" with typed confirmation); **Advanced** (collapsed: thresholds, model names, link to Developer view).

- [ ] **Step 1:** Settings read/write through `/api/v2/*` and the existing `/api/settings` for the advanced fields; every change shows "Saved" and audits.
- [ ] **Step 2:** Gesture editor: edits are staged, "Save" calls `PUT /api/v2/gestures`, API errors (duplicate gesture, unknown action) are shown next to the slot; Try-it listens to `token` events and highlights the slot.
- [ ] **Step 3:** Verify in the browser: change a gesture, Try-it with `POST /api/gesture {token:"L:double"}`, reset defaults; screenshots.
- [ ] **Step 4: Commit** `feat: dashboard v2 Settings and gesture editor`.

### Task 18: First-run setup

**Files:** Create `web/js/views/onboarding.js`, `web/js/components/{Stepper,LevelMeter,HealthRow}.js`; Modify `assistant/buds_assistant/dashboard/api_v2.py` (`POST /api/v2/setup/mic-check`, `POST /api/v2/setup/enroll-self`, `GET/POST /api/v2/setup/done`).

Steps (spec 8.2), each skippable except enrolment: 1 Health check (rows from `/health` with one-click fixes where possible: "Start Ollama", "Download model" shows the exact command); 2 Connect the buds (live status from `ui_state`, tells the user to disconnect the phone); 3 Mic check ("have someone speak 1 m away": `mic-check` records 6 s from the buds mic and the Mac mic via `sk.record_sample`-style capture, returns `{buds: {snr_db, level}, mac: {...}, recommend: "buds"|"mac"}` using `budslab.audio` metrics, sets the recommended capture source in config); 4 Enrol "You" (20 s guided reading prompt, live level meter, consent note pre-filled "My own voice", similar-voice kindness text); 5 Learn the gestures (practice screen: shows each tap as detected and what it would do; checks off all 8); 6 Privacy choices (remember, recording off by default, retention in words); 7 Try it ("Say: what time is it" then "Say: I'll send the report Friday" and shows the Noted whisper appearing in the feed).

- [ ] **Step 1: Failing API tests** for `mic-check` (inject a fake capture function; recommends the source with higher SNR), `enroll-self` (creates person named `cfg.self_name` with consent note; 400 if too short), `setup/done` persistence in `data/setup.json`.
- [ ] **Step 2: Implement API; build the stepper UI** with each step's state kept in the store so a refresh resumes.
- [ ] **Step 3: Verify in the browser** end to end in simulate mode using `wav_base64` enrolment from the demo voice; time the run (target: under 5 minutes human time, unaided); record a GIF `docs/design/screenshots/setup.gif`.
- [ ] **Step 4: Commit** `feat: dashboard v2 first-run setup`.

### Task 19: Developer view, polish pass, acceptance

**Files:** Create `web/js/views/developer.js`; Modify `docs/`.

- [ ] **Step 1: Developer view** (hidden until toggled in Settings > Advanced or `#/dev`): links to `/dev/` (the v1 analysis dashboard, unchanged), plus new panels: latency histograms by stage (from `ui_state.timings` if present; otherwise "no data yet"), full decision log table (`/api/v2/autopilot/feed?n=500`), audit table, model readiness.
- [ ] **Step 2: Polish checklist** (each verified in the browser): no `alert/confirm/prompt` anywhere (`grep -rn "alert(\|confirm(\|prompt(" web/js` returns nothing); every empty state has an action; every error path shows a fix; focus order and visible focus rings; contrast AA for text in both themes (spot check with the `design:accessibility-review` skill); reduced-motion; 360/390/768/1280 px widths; Ollama-down and buds-disconnected banners; WebSocket drop shows "Reconnecting" and recovers.
- [ ] **Step 3: Acceptance run** (spec 12 dashboard rows): a person who has not seen the product completes setup + a first Ask within 5 minutes (record the attempt in `docs/design/screenshots/acceptance.md`; if no second person is available, run the scripted walkthrough and state that clearly); "all non-developer tasks completable without leaving Home/People/Library/Settings" checked against a written task list (ask, replay, mark, enrol, name a voice, forget, change sensitivity, remap a gesture, export, delete everything).
- [ ] **Step 4:** Full test suite; update `assistant/README.md` (screens, run command, `?demo=1`); update `docs/hardware-checklist-v2.md` with dashboard-on-real-buds items; commit `feat: dashboard v2 developer view, polish and acceptance`.

---

## Self-Review

- **Spec coverage (Phases 0 to 3):** Dashboard 8.1 principles, 8.2 first-run, 8.3 screens, 8.5 frontend, push state, no pop-ups, themes, Developer view → Tasks 13–19.
- **Spec coverage, Phases 0 to 2:** 5.7 diagnosis → Task 0 + spec 18.1; 3 modes → Task 4; 4.2 map → Task 1; 4.1 anti-accident → Task 2; 4.3 contextual → Tasks 3, 10; 4.4 earcons → Task 5; 4.6 button map → Task 7; 9.2 residency → Task 6; UiState → Task 8; 5.2 A1–A5, 5.4 delivery, 5.5 sensitivity, 5.6 cold start, 5.8 log, 5.9 acceptance → Tasks 9–11. Deliberately deferred: 4.6 item 1 (media-key check, hardware, in `phase0-v2.md`), 5.8 *UI* feed (Phase 3), A2 general-knowledge/LLM answers and A6 (the engine's `question` trigger uses memory only; LLM-backed A2 is a Phase 6 item, noted so cold-start value in this phase comes from A3 and A5), remote-profile "still for 1 s" and lid-closed pocket safety (needs wear/motion data; the wear guard in Task 2 is the only protection until hardware testing shows more is needed).
- **Type consistency:** `Hint(text, trigger, person_id, sources, id)` gains `kind`, `ts`, `fact_id` (Tasks 9, 10); `GestureContext.intercept(gesture, now, speaking)` same in Tasks 3, 4, 10; `ModeManager.context` / `.touch` / `.handlers` used identically in Tasks 4 and 10; `store.log_decision` / `decisions` signatures match between Tasks 9, 10, 11; action names match the Task 1 yaml.
- **Known gap to confirm at execution:** Task 4 Step 1 grep decides the exact blast radius of the rename; Task 8 Step 4 requires reading the `/ws` handler first; `bridge.py` wording for the banner (Task 8) must be read, not guessed.

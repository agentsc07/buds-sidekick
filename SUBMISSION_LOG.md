# Submission log

## Task list
- [x] Step 0 Read docs, run fast tests, record state and gaps
- [x] Step 1 Scope freeze (Interpreter: finish or flag-hide)
- [x] Step 2 Dashboard polish (onboarding, empty/error states, jargon)
- [~] Step 3 Evaluation: synthetic numbers done; real recordings pending (docs/validation/recording-script.md)
- [~] Step 4 Packaging: pyproject + `buds-sidekick` + setup done; .app/.dmg and Release pending
- [ ] Step 5 Landing page (site/ on Vercel)
- [ ] Step 6 README, docs/report.md, docs/demo-script.md, links

## Step 0: state and gaps (2026-10-26)
- Docs read: README, assistant/README, docs/README, architecture, spec-v3-latency, voice-eval.
- Repo: branch v2, no git remote yet, `gh` logged in as agentsc07. Ollama running with qwen3.5:4b(-mlx) present.
- No `pyproject.toml`, no pipx/briefcase installed, no `site/`, no eval numbers except speaker EER (docs/validation/voice-eval.md)
  and a latency spec (Interpreter median 5.8-6.6 s vs 2.5-3.0 s target: not met).
- Known gaps from the docs: speaker accuracy on real people unmeasured; Telugu from real speakers unmeasured; Interpreter latency above target.

### Decision: environment
- The repo lives on iCloud-synced Desktop. 982 of 7413 files in `.venv/` were evicted ("dataless") and iCloud's file provider hangs
  when reading them, so pytest hung at start-up (reading `*.dist-info/RECORD`). Not a code problem.
- Workaround: new virtualenv outside Desktop at `~/.venvs/buds` (same dependencies). The old `.venv/` is left untouched.
- Recommended for the user: move the project out of Desktop/iCloud (or turn off "Desktop & Documents" sync) before packaging.

### Step 0 result
- Fast tests: **420 passed**, 3 deselected (slow), 204 s, on the new venv `~/.venvs/buds`.

## Step 1: scope freeze (decision: HIDE live voice Translate, ship text/typed translation)
- The live Interpreter exists and works end to end, but the measured median is 5.8-6.6 s against a 2.5-3.0 s target (docs/specs/spec-v3-latency.md),
  it needs a quiet Mac (3-10x slower under load), 19 s cold start, and Telugu from real speakers is unmeasured. Not reliable in 1 day.
- Chosen: flag `live_translation` (config, default **false**). Off: the Translate mode switch is hidden, `set_mode("interpreter")` is refused with a plain message,
  the hold gesture is a no-op with the error sound. Always available: the Translate box on Home (type English or Telugu, hear it) and the
  voice/typed command "translate to Telugu: ...". Turn on with `live_translation: true` in `config/sidekick.yaml` (experimental).
- Tests updated; new test pins the default.

## Step 2: polish (done)
- Screens reviewed with headless Chrome screenshots (the Chrome extension was not connected). Existing UI was already consistent.
- Added: first-run downloads with live progress (`POST/GET /api/v2/setup/download`, `core/pulls.py`) for the Ollama models and voice model; setup checks use plain
  words ("Thinking engine (Ollama)", "Language skills", "Voice recognition"); "Practice mode" pill instead of a warning in `--simulate`;
  "Mic off" wording when not listening; typed Translate box on Home (layout row fixed); gesture list says Translate is off.
- Bugs found and fixed while measuring: (1) FileSource drifted ~5% against real time (summed sleeps), (2) Whisper heard "Sidekick" as "I take it", so Ask
  never fired; added a vocabulary prompt (`transcribe.VOCAB`).

## Step 3: evaluation (synthetic part done)
- `eval/submission_eval.py` (`wer`, `latency`, `autopilot`, `record`). Results in `docs/validation/eval-results.json`:
  EN WER 4.9% (6/122), TE WER 9.5% (2/21; both word-split spelling), whisper 2.0 s, Ask answer 2.1 s, quick command 2.2 s (n=5, load ~5),
  scripted Autopilot precision 8/8 (rules only; not a human judgement). Speaker EER table kept (docs/validation/voice-eval.md).
- Needs the user: real-voice clips, a rated Autopilot session, buds latency. Exact script: `docs/validation/recording-script.md`.

## Step 4: packaging
- Root `pyproject.toml` (name `buds-sidekick`, entry point `buds-sidekick`), packages `buds_assistant` + `budslab`; config yaml moved INTO the package
  (`assistant/buds_assistant/config/`) so installs work. Installed mode keeps data in `~/Library/Application Support/Buds Sidekick`; a checkout keeps it in `assistant/`.
- Verified: wheel built, installed into a clean venv, `buds-sidekick setup --check` runs, `buds-sidekick --simulate` serves the dashboard.
- Setup script = `buds-sidekick setup` (Ollama check, `ollama pull` for missing models, voice-model download, Whisper warm-up).
- Decision: pipx is not installed here, so the wheel was verified with venv + pip (same artifact). Briefcase/py2app deferred.

## Git decision
- History holds a 185 MB blob (`assistant/models/ggml-te-small.bin`) that GitHub rejects. Not rewriting history. The old branches stay local and untouched;
  the GitHub `main` is an orphan snapshot of the current tree (branch `submission`).

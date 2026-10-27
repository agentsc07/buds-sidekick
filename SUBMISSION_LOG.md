# Submission log

## Task list
- [x] Step 0 Read docs, run fast tests, record state and gaps
- [x] Step 1 Scope freeze (Interpreter: finish or flag-hide)
- [x] Step 2 Dashboard polish (onboarding, empty/error states, jargon)
- [~] Step 3 Evaluation: synthetic numbers done; real recordings pending (docs/validation/recording-script.md)
- [x] Step 4 Packaging: pyproject, `buds-sidekick`, setup, native-window .app/.dmg, GitHub Release v1.0.1 (live)
- [x] Step 5 Landing page: https://site-psi-five-93.vercel.app (demo at /demo)
- [x] Step 6 README, report, demo script, links (demo video removed from the site; real-voice numbers pending)

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

## Step 5: landing page
- `site/` (static: index.html, results.json copied from docs/validation/eval-results.json, vercel.json). Checked locally with a headless-Chrome screenshot.
  Demo video is a placeholder (search `VIDEO_URL`). Install links point at github.com/agentsc07/buds-sidekick.

## BLOCKED (needs the user)
- Creating the GitHub repo and pushing (`gh repo create agentsc07/buds-sidekick --private`, `git push origin submission:main`) was denied by the permission
  classifier ("public data-sharing upload"), so nothing has been published. Also not done for the same reason: Vercel deploy of `site/`, GitHub Release.
- Local state: branch `submission` (orphan snapshot, ready to push); no remote configured yet.

## Direct app / website (user asked after the GitHub step)
- A pure website cannot run it (needs mic, Bluetooth, local models). Instead: (1) `site/demo/` is the real dashboard served statically on fixture data
  ("Try the live demo" on the landing page; copy of `dashboard/web`, re-copy after UI changes); (2) `packaging/build_app.sh` builds `dist/Buds-Sidekick-1.0.0.dmg`
  (unsigned launcher .app: installs the bundled wheel into its own venv on first run, runs `buds-sidekick setup`, opens the dashboard). Needs Python 3.11+ and Ollama on the Mac.
  Not py2app/Briefcase: ctranslate2/onnx/sherpa wheels make a frozen bundle fragile; this is the reliable option. Launcher syntax-checked, not run end to end.

## Secrets / personal-data scan (before going public)
- Working tree + the pushed commit (`submission`, branch `main` on GitHub): no keys/tokens/private keys/`.env`/passwords (regex scan), no personal paths or email,
  no recordings (`*.wav`), no databases (`*.db`), no enrolment/people data. Two 53-byte protocol packet fixtures (`lab/tests/*.bin`: battery/firmware status) are harmless.
  Placeholder MAC `AA:BB:CC:DD:EE:FF` only in help text.
- Sensitive files that exist ONLY on disk and are git-ignored (not moved, because moving them would wipe your enrolment and conversations):
  `assistant/data/` (people DB, voiceprints, notes), `assistant/data-sim/` (synthetic), `lab/data/` (earbud sessions). `.gitignore` now also covers `*.db`, `*.wav`, `*.jsonl`,
  `.env`, `*.pem`, `*.key`, `_holding/`, `docs/validation/clips/` (your recordings).
- Local-only OLD history (branches `main`, `v2`) contains `assistant/data-sim/sidekick.db` and the 185 MB model files. They were never pushed; **push only
  `submission:main`, never `--all` or the old branches.**

## Site restructure + test
- `site/`: hero (Try the live demo -> /demo, Download for Mac -> releases/latest), video placeholder + 3 screenshots, features, results, privacy, collapsed "For developers"
  (terminal install, notes it needs a public repo; architecture). `vercel.json`: cleanUrls + trailingSlash (so `/demo` -> `/demo/` and relative assets resolve).
  `site/sync-demo.sh` refreshes `site/demo/` from the dashboard. `site/tests/check_site.py` (Playwright + system Chrome): both buttons, /demo, People page, zero console errors: PASS.

## STATUS (2026-10-26, end of session)
- LIVE: repo https://github.com/agentsc07/buds-sidekick (public), Release v1.0.1 (.dmg, native window, no Terminal), site https://site-psi-five-93.vercel.app (+ /demo). The BLOCKED section above is resolved (user ran the login commands).
- Remaining (user): real-voice clips + rated Autopilot session (docs/validation/recording-script.md), demo video (replace VIDEO_URL in site/index.html, redeploy), try the .dmg end to end.

## Reversal after user feedback (v1.0.2)
- User wants live Translate back: switch + "They speak" / "I hear" dropdowns (Telugu/English), translated speech in the ear. `live_translation` default now TRUE,
  `interpreter_from/to` config + `POST /api/v2/interpreter {src,dst}`; typed box shows only when live is off. The scope freeze (Step 1) is superseded: shipped as experimental, latency 5.8-6.6 s documented.
- App defaulted to practice mode because buds were renamed ("Sai's Buds FE"); detection now matches any connected device with "buds" in its name, and the window menu has
  "Use my earbuds" / "Practice mode" (remembered in app.json).

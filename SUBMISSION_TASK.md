# Submission task: Buds Sidekick (MAIN project)

Context: this is my main project for the Applied AI & Data Science course. It is a local voice-aware assistant for Galaxy Buds FE + MacBook (see README.md, docs/architecture.md, docs/validation/). It has to be submitted soon and ideally deployed. It must look like a polished product, not a prototype.

## Steps
0. Read README.md, assistant/README.md, docs/README.md, docs/architecture.md and the latest spec/plan. Run the fast tests (`-m "not slow"`). Write the current state and gaps into `SUBMISSION_LOG.md`.
1. **Scope freeze.** The voice-to-voice Interpreter (Phase 5) is unfinished. If it can work reliably in about 1 day, finish it; otherwise hide it behind a flag and present text translation only. Tell me which you chose.
2. **Polish pass** on the dashboard (http://127.0.0.1:8770): first-run onboarding (connect buds, enrol your voice, pull Ollama models with progress), clear empty/error states, no developer-facing jargon. Fix any rough edges you find in Listen, Autopilot and Ask.
3. **Evaluation for the report.** Keep the speaker-ID EER table. Add: end-to-end latency (speech end to whisper/answer), ASR word error on a few Telugu and English clips, and Autopilot precision (whispers judged useful / total) from a short scripted session. Ask me to record what you need, and give me an exact script for it.
4. **Packaging.** Make it installable on another Mac: `pipx install` (pyproject entry point `buds-sidekick`) and, if feasible, a .app/.dmg via Briefcase or py2app. `--simulate` must work with no buds, so a grader can try it. A setup script checks for Ollama and pulls the models. Publish it as a GitHub Release.
5. **Landing page** on Vercel (static, separate `site/` folder): pitch, demo video embed (placeholder until I record), architecture diagram, the eval numbers, install instructions, privacy ("everything runs locally").
6. Deliverables below, plus the demo script showing: Listen, who-is-talking, Ask, an Autopilot whisper, Telugu↔English translation.

## Rules
- Never delete files. Move anything unwanted into `_holding/` inside this repo.
- Never commit secrets (`*.pem`, `.env`, keys). Check `git status` and `.gitignore` before every commit.
- Push to `github.com/agentsc07/<repo>` with `gh`. Ask me before making the repo public or publishing a package.
- Ask me only when blocked on something only I can do (hardware, accounts, labelling, listening). Otherwise decide, and note the decision in `SUBMISSION_LOG.md`.
- Keep a task list. Commit small and often.

## Deliverables (every project)
1. `README.md` rewritten for a grader: one-line pitch, the problem, how it works (diagram), **results with numbers**, live links, how to run.
2. `docs/report.md`: one page. Problem, method, evaluation, limitations, next steps.
3. `docs/demo-script.md`: a 2-minute screen-recording script, shot by shot.
4. All deployed links working and listed at the top of the README.

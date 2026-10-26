# Spec v3-B: Product polish: UI, information architecture, controls, voice of the assistant

Status: written 2026-10-04. Scope: `dashboard/web/**`, assistant phrasing in `brain.py`, `autopilot.py`, `policy.py`, `output.py`,
`dashboard/api_v2.py` (small additions). Companion: `docs/specs/spec-v3-voice.md`.

## 1. Feedback this answers
- "The UI doesn't look professional" -> references: calm gradient hero with one clear focal element (meditation app), frosted glass
  cards with big numerals (finance app), a living orb + waveform for the assistant (Dola). Dark and light themes.
- "The goal is to simplify: too many options" -> cut every control that is not needed daily; defaults decide the rest.
- "No shortcuts/gestures tab: that is the main part" -> a first-class **Controls** screen.
- "The assistant voice can be polite" -> a written voice-and-tone guide applied to every spoken and written line.
- "The tab organisation isn't great" -> new information architecture below.
- Live bug fixed first: false "language model is not running" banner in Interpreter mode.

## 2. Principles
1. **One screen, one job.** Home is for being with the assistant. Everything else is a place to look something up.
2. **Defaults over settings.** A setting exists only if a normal person would change it. The rest moves to Advanced.
3. **Show the state, not the plumbing.** "Listening, Autopilot on" and a living orb, not model names and event feeds.
4. **Every spoken line is polite, short, and useful.**
5. **Works with the buds first.** Anything you can do on screen you can do with a gesture or a voice command, and the screen says how.

## 3. Information architecture (5 places, was 7)
| Place | Contains | Replaces |
|---|---|---|
| **Home** | the orb (state), the three modes + Private, Ask bar, live conversation with whispers, a compact "up next" strip | Home |
| **Day** | Agenda (calendar), To-dos (incl. promises you made, with who/when), Reminders; one "Add" sheet | My day, Library > promises |
| **People** | voices, Voice health, per-person page: what they said, promises, conversations, forget | People, Library > conversations |
| **Controls** | visual buds with every gesture and its action, editable by tap, "Try it" live highlight, voice commands list, earcon legend | Settings > gestures, scattered help |
| **Settings** | 6 rows only: Voice and microphones, Assistant (how proactive, voice), Privacy (keep nothing / forget all), Appearance, Connection (buds, models), Advanced (opens Developer) | Settings (long form), Developer |

Navigation: left rail on desktop (icons + labels, 5 items, Settings at the bottom), bottom bar below 720 px. No nested tabs.
Keyboard: `g h/d/p/c/s`, `?` for help, `Space` push-to-ask when the Ask bar is not focused.

## 4. Visual system
- **Type:** system UI stack (SF Pro on macOS; offline-safe). Scale 13/15/17/22/34/52; hero numerals tabular. Sentence case everywhere.
- **Colour (tokens, light and dark):**
  - Dark: canvas `#0B0A12`, surface `rgba(255,255,255,.06)` with 1px `rgba(255,255,255,.10)` border and 24 px blur, text `#F4F3F8`.
  - Light: canvas `#F3F5F8` with soft cloud gradient, surface `rgba(255,255,255,.72)`, text `#14151A`.
  - Accent gradient (the one expressive thing): violet `#7C5CFF` -> magenta `#E04BD2` -> warm `#FF8A4C`. Semantic: ok `#2DBE7E`, warn `#F2A33A`, bad `#EF5B5B`.
- **Radius:** 28 px hero/cards, 16 px controls, full pills for chips. **Elevation:** blur + border, no hard shadows.
- **The orb** (Home hero, ~220 px): layered blurred conic gradients rendered with CSS/canvas, no images.
  States: *Standby* (dim, slow breathing), *Listening* (soft ripples that react to mic level), *Autopilot* (ripples + a thin ring),
  *Interpreter* (two-tone orb that splits left/right while translating), *Private* (grey, still), *Speaking* (pulse in time with TTS),
  *Thinking* (slow rotate). Respects `prefers-reduced-motion` (static gradient with state colour).
- **Mode control:** three large pills under the orb (Listen, Autopilot, Interpreter) and a lock button for Private; selected pill
  carries the gradient. Memory level is a single "Remembering / Not remembering" toggle, not three levels (recording stays hidden).
- **Live conversation:** large, quiet type; speaker avatar chips with colour; whispers appear as inset glass notes on the right with
  the reason on tap; unsure lines are dimmed. Max 8 lines visible, older fade out; "Open full transcript" goes to the person/conversation.
- **Banners:** one slot, at most one message at a time, ordered by importance, each with exactly one action button. Transient states
  (model restoring, reconnecting) show only after 8 s.
- **Empty states** say what to do ("Say 'I'll send the report on Friday' and I'll add it to your to-dos").
- **Motion:** only orb, mode switch, sheet open/close. Nothing animates on page load except the orb.

## 5. Controls screen (the main feature)
- Centre: an illustration of the two buds (SVG) with a segmented list per side: single, double, triple, hold -> action name.
- Tap a gesture row -> a sheet with the action choices (plain language: "Ask a question", "Replay the last 20 seconds", "Private on/off"...).
- **Try it:** when open, real gestures from the buds light up the row and show the action without executing it (already supported by
  the backend try-it mode).
- Two profiles shown as a switch: *In ear* and *Remote (buds out)*.
- Below: "Things you can say" (voice commands for Ask: calendar, to-do, reminders, "who is this", translate) with tap-to-try, and the
  sound legend (what each earcon means) with a play button.
- A one-time card on Home on first run: "Tap your left bud once to ask me anything."
- Reset to defaults button; nothing else.

## 6. Voice of the assistant (spoken and written)
Rules: polite, warm, brief (<= 12 words for whispers), first person, no jargon, never blames the user, always says what happens next.
Use "please", "I've", "Would you like"; avoid "Noted:" telegrams and robotic labels.
| Situation | Before | After |
|---|---|---|
| Promise captured | "Noted: send the report, Friday. Added to your to-do." | "I've added 'send the report' for Friday to your to-dos." |
| Clash | "Heads up, Standup then." | "Just so you know, you have Standup then." |
| Availability | "You're free at 2." | "You're free at 2 tomorrow, shall I say yes?" (spoken to the user only) |
| Meeting soon | "Standup in 10 minutes" | "Your Standup starts in 10 minutes." |
| Didn't hear | "I did not catch that." | "Sorry, I didn't catch that. Could you say it again?" |
| Unknown voice | "unknown_voice" | "I don't recognise this voice yet." |
| Interpreter start | (silent) | "Interpreter is on. I'll translate as they speak." |
| Error | stack-ish text | "I can't reach the language model right now. Quick commands still work." |
A single `voice_lines.py` holds every line (testable, one place to tune); a test fails if a line exceeds 14 words or lacks terminal punctuation.

## 7. Settings: what is removed from view
Move to Advanced (hidden by default): speaker threshold, margins, segment lengths, model names, Telugu STT toggle (always on while
Interpreter is on), hint gaps/budgets, ring seconds, button remap. Autopilot sensitivity becomes 3 plain choices: *Quiet, Helpful, Proactive*.

## 8. Voice enrolment UX (shared with specv3-voice R1)
Inline "Add a voice" sheet: name, consent line, a big record button with level meter and timer (20 s guide with a sentence to read),
immediate playback ("Hear it back"), Record again / Use this. Choice at the top: *New person* or *Add to <existing person>*. The same
sheet is used from Setup, People and from a transcript line ("This is...").

## 9. Acceptance
1. Browser self-test passes at 1440, 1024 and 390 px, light and dark; no horizontal scroll; every nav item reachable by keyboard.
2. Screenshot review of Home (5 orb states), Day, People, Controls, Settings in both themes against this spec by a fresh reviewer.
3. Task tests: ask by typing, change a gesture, try a gesture, add a to-do, add a voice to an existing person, switch Autopilot level,
   turn on Interpreter and see its state: each in <= 3 clicks from Home.
4. `voice_lines` test passes; no remaining string in the code base matching the old robotic lines.
5. Settings main page has <= 6 rows; Advanced reachable in one click and hidden from the main page.
6. No console errors and no banner flicker when entering/leaving Interpreter (regression test for the false "model not running" banner).

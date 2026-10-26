# Buds Sidekick v2: from working prototype to polished product

*Spec v2. Builds on `docs/specs/product-spec.md` (v1 + Addendum v1.1) and the current `assistant/` code. Written 2026-10-02 after the first hands-on trial of v1.*

**What I reviewed to write this:** `README.md`, `docs/specs/product-spec.md`, the dashboard (`index.html`, `app.js`). I did **not** see the Python pipeline, policy or mode code, so where this spec says "likely cause" or "reuse", the implementer must verify against the code first.

---

## 1. Summary

v1 proved the idea: the buds work as a controller, the assistant listens, identifies voices, remembers, answers and translates. The first trial says the answers are good but the **experience is not**: it feels like a test rig, Autopilot is silent, translation is text-oriented, and the intelligence is not visible.

v2 is a **product-quality pass**. It does not add many new capabilities. It makes the existing ones *smooth, legible, and smarter*, and changes five things on purpose.

| # | Feedback from v1 trial | v2 decision | Section |
|---|---|---|---|
| 1 | Translation should be a **mode**, **live**, **voice-to-voice in the ear**, not voice-to-text | New first-class **Interpreter mode**: speech in, translated speech out, phrase by phrase, with a latency budget and a backlog policy. Text is secondary. | 6 |
| 2 | Dashboard is for analysis; make it a **user product** | Complete redesign: Home / People / Library / Settings, onboarding, plain language. Analysis tools move to a hidden Developer view. | 8 |
| 3 | Experience is good but **not smooth or polished** | Explicit polish requirements: no unexplained silence, model residency, earcon system, push-based UI state, self-healing, latency budgets. | 9 |
| 4 | Needs **more intelligence**; unsure whether person tagging works | LLM intent router with tools, live conversation understanding, name-mention inference, visible "who's here" with confidence, post-conversation review. | 7 |
| 5 | **Reconsider modes and gestures** (e.g. what single click should do) | Five modes, one clear gesture map, contextual gestures, plus voice commands ("Sidekick, start recording"). | 3, 4 |
| 6 | **Autopilot doesn't whisper anything**; explain its scope and goal in detail | Full Autopilot definition, trigger catalogue, delivery rules, "why was it silent" panel, and a root-cause step before any new work. | 5 |

---

## 2. Product principles

1. **No unexplained silence.** Every gesture, command and mode change gets feedback within 200 ms (a sound, or a short phrase). If the assistant decides not to whisper, the dashboard can say why.
2. **One mental model.** Left bud = *talk to the assistant*. Right bud = *control the session*. The same gesture does the same thing in the ear and out of the ear.
3. **Low-stakes gestures on easy taps.** The most frequent, most harmless actions get single/double taps. Rare or consequential actions get hold/triple, voice, or the dashboard.
4. **Calm by default.** Autopilot should feel like a good colleague tapping your shoulder rarely, not a notification stream.
5. **Local-first, honest about confidence.** Everything stays on the Mac. When the assistant is unsure (a name, a translation, a fact), it says so.
6. **Product language.** Users never see words like cluster, embedding, retention days, or STT in the main UI.
7. **Speed is a feature.** Every task has a latency budget (section 9.3) and is measured.

---

## 3. Modes (final set)

v1 had Idle, Manual, Conversation, Auto, Archive, Private. That is too many and the names are internal. v2 has **five modes** plus **one memory setting**.

### 3.1 The five modes

| Mode | In plain words | Mic | What it does |
|---|---|---|---|
| **Standby** | "On call, not listening" | Closed (opens briefly for Ask) | Gestures and voice-free asks work. Music plays normally in the buds. |
| **Listen** | "Following the conversation" | Open | Live transcript, who's who, replay, marks, catch-me-up, memory. Never speaks unless asked. |
| **Autopilot** | "Listening and helping" | Open | Everything in Listen **plus** proactive whispers (section 5). |
| **Interpreter** | "Translating live" | Open (Mac mic by default, see 6.4) | Voice-to-voice translation in the ear (section 6). |
| **Private** | "Off the record" | Hard closed | Mic closed, replay buffer wiped, nothing stored. Always one gesture away. |

**Ask** is not a mode. It is an *action* available in Standby, Listen and Autopilot: one tap, speak, answer.

### 3.2 Rules

- Exactly one mode is active and always visible (dashboard header, menu-bar icon) and audible (earcon + short phrase on change, e.g. "Autopilot on").
- **Autopilot is Listen plus whispers**, so switching it on from Standby starts Listen automatically. Switching it off returns to Listen.
- **Interpreter and Autopilot are mutually exclusive** (two sources of whispering would collide). Entering Interpreter pauses Autopilot and restores it on exit.
- **Private always wins** and can be entered from any mode. Leaving Private returns to Standby, never straight to a listening mode.
- Wear state: both buds out is **not** a mode change. It switches the *placement* (ear to remote, see 4.2). Taking one bud out keeps the current mode and turns ambient sound on (as in v1).
- Buds out of range or disconnected: modes that need the buds pause with a dashboard banner, and resume on reconnect.

### 3.3 Memory setting (a toggle on Listen/Autopilot, not a mode)

| Level | Meaning | Default |
|---|---|---|
| **Live only** | Nothing is saved after the conversation ends. | |
| **Remember** | Save transcripts, facts and commitments for people who have a "remember" setting. Unknown voices are never saved. | **On** |
| **Recording** | Also save the raw audio of this conversation as a recording file. Requires an explicit user action (gesture-free: voice command or dashboard button), plays "Recording started" and repeats a soft reminder cue every few minutes. | Off |

"Start recording" / "stop recording" (voice or dashboard) moves between Remember and Recording for the current conversation only. Recordings are separate from searchable memory: words from unknown voices exist only in the recording file, are not voiceprinted, and do not create facts or people. Retention for recordings defaults to 30 days and is visible in the Library. The user is responsible for consent where they live; the first time Recording is used, the dashboard shows a one-time plain-language notice, and every Recording start is written to the audit log.

---

## 4. Controls

### 4.1 Gesture principles

The buds give us single, double, triple and hold per side (hold arrives as a burst, so it is debounced into a toggle, as in v1). That is eight slots. They go to the actions people need *most often while in a conversation*; everything else uses voice or the dashboard.

- **Single tap = the easiest action.** Single taps are also the most likely to fire by accident (SoundGuys notes the pads shift the buds). So single taps must be cheap if mistaken.
- **Hold = deliberate toggles** (a mode that stays on).
- **Triple = rare but important**, hard to trigger by accident.
- Any tap while the assistant is *speaking* stops it (contextual, see 4.3), so "stop" needs no slot.
- Anti-accident filter: ignore touches within 1 s of insertion or removal, and ignore bursts of more than 3 touches in 1 s (pocket / adjusting).

### 4.2 Gesture map (same in ear and remote)

| Gesture | Action | Why this slot |
|---|---|---|
| **Left single** | **Ask**: chime, speak, auto-stops when you stop. No speech within 3 s cancels silently with a soft "never mind" tone. | Most frequent action. An accidental tap costs nothing visible. |
| **Left double** | **Replay** the last N seconds (default 8). Tap again within 6 s: escalate to **catch me up** (spoken summary of the last 2 minutes). | Frequent attention safety net. |
| **Left triple** | **Private mode** on/off. | Urgent and deliberate, hard to trigger by accident. |
| **Left hold** | **Interpreter** on/off. | A deliberate, sticky mode. |
| **Right single** | **Mark this moment** (bookmark attached to who is speaking). | Frequent in meetings/lectures, harmless if mis-tapped. |
| **Right double** | **Autopilot** on/off. | Toggle you use several times a day. |
| **Right triple** | **Who is talking / who's here?** | Quick in-conversation need. |
| **Right hold** | **Listen** on/off. | Deliberate toggle for the session. |

Spoken confirmation after every mode toggle ("Listening", "Autopilot on", "Interpreter, English to Telugu", "Private"), preceded by an earcon so it also works at a glance.

**Remote profile (both buds out of the ears, buds as a clicker):** identical map. Differences: capture comes from the Mac mic and audio plays on the Mac speakers (as in v1). Extra pocket-safety: single-tap actions require the buds to have been still for 1 s, and the profile is disabled while the case lid is closed.

### 4.3 Contextual gestures

These apply for a few seconds only, so they add no new slots.

| Situation | Gesture | Effect |
|---|---|---|
| Assistant is speaking (answer, replay, whisper) | Any single tap | Stop speaking. |
| Within 4 s after a **whisper** | Any single tap | "Tell me more" (a longer version of the same hint). |
| Within 4 s after a whisper | Any double tap | "Not useful": dismiss, and lower that hint type's priority for 10 minutes. Counts as feedback. |
| Within 5 s after Autopilot **noted a commitment** ("Noted: send report to Ravi by Friday") | Any double tap | Undo. Silence = accepted. |
| Within 6 s after **Replay** | Left double | Escalate to catch-me-up. |

### 4.4 Feedback sounds ("earcons")

One designed set of short, soft sounds, consistent across the product: mode on, mode off, listening start, listening stop, gesture accepted, command recognised, whisper incoming, noted, error, recording reminder. Spoken phrases are short (under 5 words) and only for mode changes and errors. Replace the v1 chimes with this set. All sounds are generated or bundled locally.

### 4.5 Voice commands (the "start recording" requirement)

In Listen and Autopilot, the user can control the assistant by voice without touching the buds.

- **Wake phrase:** configurable, default **"Sidekick"**. Detected from the live transcript stream, not a separate always-on engine, to start (a dedicated local wake-word model is an optional later upgrade).
- **Speaker gate:** commands are accepted **only from the enrolled wearer ("Me")**, matched by voice. Someone else saying "Sidekick" does nothing.
- **Acknowledgement:** a short earcon the instant the command is recognised, then the action.
- **Fixed commands** (fast path, no LLM):

| Say | Does |
|---|---|
| "Sidekick, start recording" / "stop recording" | Recording level on/off for this conversation (3.3). |
| "Sidekick, remember this" / "mark that" | Mark this moment. |
| "Sidekick, replay" / "say that again" | Replay. |
| "Sidekick, catch me up" | Spoken summary of the last 2 minutes. |
| "Sidekick, who's that?" | Who's talking / who's here. |
| "Sidekick, autopilot on / off" | Autopilot. |
| "Sidekick, translate to Telugu" / "interpreter on / off" | Interpreter. |
| "Sidekick, private mode" | Private. |
| "Sidekick, stop" | Stop speaking. |

- **Free-form:** anything else after the wake phrase goes to the intent router (7.1): "what did Ravi say about the budget?", "remind me to call Anita tomorrow", "summarise this conversation", "take a note: ...".
- In **Standby** there is no open mic, so voice commands are not available. Ask (left single) is the way in.
- Command misfires are logged with the transcript so the wake logic can be tuned. A command that is ambiguous is not executed; the assistant asks one short clarifying question.

### 4.6 The buds' own default actions

The buds keep factory behaviour (single = play/pause, double = next, hold = noise mode). v2 must, on start:

1. **Verify** whether single/double/triple also reach macOS as media keys (v1 observed that AVRCP media keys did not show up, so this may be a non-issue; confirm and record the result).
2. Remap touch-and-hold so it does not toggle noise mode behind our back (using the allowlisted touchpad mapping command), and **restore the user's original mapping on exit**, including after a crash (store the original mapping on disk first).
3. If media keys do reach the Mac and conflict, swallow them while a mode other than Standby is active, and say so in Settings.

### 4.7 Customisation

A visual editor in Settings: a diagram of two buds, a dropdown per gesture, a "try it" mode that shows the live detected gesture and what it would do. Reset to defaults button. The gesture map is still stored in `gestures.yaml` for power users.

---

## 5. Autopilot: scope and goal

### 5.1 The goal in one sentence

**Autopilot is the assistant that taps your shoulder.** While you are in a conversation, it quietly gives you one short, useful whisper at the right moment, and stays silent the rest of the time.

Success is not "it talks a lot". Success is: *you look back at a day and think "those whispers saved me a few awkward moments", and you never once wanted to turn it off.*

### 5.2 What Autopilot is for (the jobs)

| # | Job | Example whisper | Needs | Default |
|---|---|---|---|---|
| A1 | **Who is this** | "Ravi. He owes you the Q3 report." | Voice matched to a known person | On |
| A2 | **Answer assist**: someone asks you a question and the answer is known | Priya: "When's the demo?" → "Demo is October 14, you said Tuesday." | Question detected + memory or a confident fact | On |
| A3 | **Commitment capture**: you promise something | You: "I'll send it Friday." → "Noted: send report to Ravi, Friday." | Your own speech understood; people tagged | On |
| A4 | **Commitment reminder**: a stored promise becomes relevant | Ravi speaks → "You promised him the slides." | Stored commitments | On |
| A5 | **Missed-name rescue**: you are addressed or someone is mentioned and you may not know them | "Anita is the new finance lead, from last week's call." | People memory | On |
| A6 | **Term helper**: unfamiliar acronym or term | "ARR: annual recurring revenue." | LLM, rate limited, user opt-in | Off |
| A7 | **Conflict check**: a claim contradicts something stored | "Earlier Ravi said Thursday, not Friday." | Memory with sources | Off (P1) |
| A8 | **Time awareness** | "Five minutes to your next meeting." | Calendar (optional) | Off (P2) |

Every whisper carries its source ("from Tuesday's call"), available on "tell me more".

### 5.3 What Autopilot is NOT

- It does not speak *for* you or write replies for you.
- It does not identify, profile or whisper about **unknown** voices.
- It does not comment on emotion, honesty or tone.
- It does not talk while you are speaking, ever.
- It does not run when Private or Interpreter is on.

### 5.4 Delivery rules

- **Never while you are speaking.** Hold the hint until the next gap; drop it if it goes stale (older than 6 s after its trigger, or the conversation has moved on).
- **One at a time**, at most one hint per 20 s and at most 12 per hour by default (per sensitivity setting below).
- **Short**: at most 12 words (A2 may use 20). Whisper-style voice, slightly quieter, with ducking so real speech is never covered.
- **Priority order** when several are ready: A3 confirmation, A2, A4, A5, A1, then the rest.
- **Debounce**: A1 once per person per 10 minutes; the same hint is never repeated.
- **Feedback loop**: contextual gestures (4.3) rate each whisper. Three "not useful" in a row halve the rate for that hint type; the dashboard shows this so it is not a black box.

### 5.5 Sensitivity (the one setting most people touch)

| Level | Behaviour |
|---|---|
| **Quiet** | Only A3 (commitment capture) and A2 (direct questions). |
| **Balanced** (default) | A1 to A5. |
| **Proactive** | Balanced plus A6 and A7, shorter cooldowns. |

Plus per-category switches (plain-language checkboxes) in Settings.

### 5.6 Day-one value (cold start problem)

Autopilot with an empty memory has little to say, which is a likely reason it felt dead. v2 must give value on day one:
- **A3 commitment capture works with no stored history**: it needs only your own words.
- **A6 term helper** and **A2 general-knowledge answers** use the local model (with a confidence gate: below the threshold, stay silent) rather than only stored facts. An optional, user-enabled web lookup (text-only query) may back A2.
- **A5** works from names mentioned in the *current* conversation.

### 5.7 Why it was silent: root-cause step (do this first)

The v1 README lists Autopilot as built but the trial heard nothing. Before building anything, reproduce and diagnose with the simulator conversation. Candidate causes to check (not asserted, I could not see the code):
1. The enable gesture was a **two-step sequence** (right single then left single) that may not register reliably.
2. All triggers required **enrolled** voices or **stored facts**, which a new user does not have.
3. Rate limits or "stale hint" expiry dropped everything.
4. The output arbiter dropped hints (it can emit "dropped: reason").
5. The buds mic did not hear other people clearly enough to detect questions or voices.
6. Autopilot never left Listen because the mode switch did not complete.

Deliverable: a written finding of which cause(s) applied, plus the fix.

### 5.8 "What did Autopilot do?" (transparency)

A live **Autopilot feed** on the Home screen and in the conversation record, in plain language:
- *Said*: "Ravi. He owes you the Q3 report." (with 👍 / 👎)
- *Noted*: "Send report to Ravi by Friday." (with undo)
- *Held back*: "Had a hint about the budget, but you were speaking." / "Skipped: too soon after the last whisper."

This is how a user (and the developer) can tell whether silence is correct.

### 5.9 Acceptance

- Replaying a scripted 10-minute, 3-person conversation yields whispers only at the labelled trigger points (precision at least 70 %), none during the wearer's speech, and at most the configured rate.
- On a **cold start** (empty memory), the same script still produces at least the A3 commitment captures.
- Every whisper has a feed entry with its trigger, source and outcome; every suppressed candidate has a reason.
- A real 30-minute dogfood session produces at least one whisper the user rates 👍, and fewer than 12 per hour.

---

## 6. Interpreter mode: live voice-to-voice translation

### 6.1 What the user experiences

Turn on Interpreter (left hold, voice, or dashboard). A short phrase says "Interpreter, Telugu to English." Someone speaks Telugu; **a moment after each phrase, you hear the English spoken in your ear**. Optionally, when you speak English, **the Telugu is spoken aloud** from the Mac for the other person (two-way). The dashboard is a secondary view only (subtitles, language switch).

### 6.2 Requirements

- **Voice in, voice out.** Output is speech in the buds, not text.
- **Phrase-level streaming**, not whole-conversation batches: segment on a pause of about 350 ms or a maximum of about 6 s, then speech to text, translate and speak.
- **Languages:** English and Telugu at launch, detected automatically per phrase, with a manual override. The language pair is pluggable (other Indian languages are an obvious next addition, subject to model quality).
- **Directions:** (a) *Listen*: their speech to my ear (default). (b) *Two-way*: also my English speech spoken in Telugu through the Mac speakers.
- **Voices:** English via a macOS voice; Telugu via *Geeta*. Voice and speed selectable.
- **Ducking, not talking over**: translated speech is queued and never overlaps the speaker's next phrase in a jarring way. Ambient sound is turned on automatically so the real speaker stays faintly audible, and restored on exit.
- **Backlog policy:** if the queue falls more than 6 s behind, speed up the voice (up to 1.25x), then merge short phrases, then skip filler. Never silently drop content: if something was skipped, say a soft "caught up" cue and keep the text in the dashboard.
- **Honest uncertainty:** if recognition confidence is low, say "unclear" with a soft tone instead of speaking a confident wrong translation.

### 6.3 Latency targets

| Step | Target |
|---|---|
| End of phrase to start of translated speech | p50 at most 2.5 s, p90 at most 4 s |
| Interpreter on, warm | at most 2 s to ready |
| Interpreter on, cold (models loading) | immediate "Starting interpreter" cue, ready within 8 s |

v1 measured Telugu speech recognition at about 2 s per clip (synthetic voice) and noted first-use stalls of 10 to 25 s when models were swapped out, so **model residency (9.2) is a hard dependency**.

### 6.4 Capture source (important design choice)

When the buds mic is open, the buds switch to call mode: audio is mono and limited to 16 kHz, so **in-ear translated voice sounds worse and the mode flip stutters**. Therefore:
- **Default for Interpreter: capture from the Mac microphone, keep the buds in normal listening mode.** The translated voice reaches your ear in higher quality, with no flip.
- **Alternative: buds mic**, for when you are away from the Mac's mic range, with a quality warning.
- The mic check in onboarding (8.2) tells the user which source hears the other person better.

### 6.5 Two-way echo control

When the Mac speakers play Telugu for the other person, the Mac mic hears it and would translate it back. Use **half-duplex**: while the Mac plays speech, ignore capture segments that overlap it, with a short tail guard. Later, consider real echo cancellation.

### 6.6 Known risks, with a fallback ladder

- Telugu speech recognition was verified only on a **clean synthetic** clip. Real speech is untested, as is Geeta's naturalness.
- **Gate:** test with at least 3 real Telugu speakers, 20 sentences each, in a quiet room. Record word error rate and "meaning preserved" rating.
- If it fails the gate, degrade in this order: (1) speak what was heard back in text form on the dashboard and say "check screen"; (2) one-way English to Telugu only; (3) typed-input mode.
- Translation quality of the local model is good for common sentences; idioms and names are weaker. Say so in Settings.

---

## 7. Intelligence upgrades

### 7.1 Intent router (replaces most rule matching)

v1's `RuleAgent` handles a fixed set of phrases. v2 adds an **LLM router with tools**, so natural requests work.

- Input: the user's utterance, current mode, the recent conversation window, who is present.
- Tools it can call: `search_memory(person, query)`, `person_brief(name)`, `summarise(window)`, `list_commitments(person)`, `add_note`, `add_reminder`, `set_mode`, `start/stop_recording`, `translate`, `replay`, `time/battery/timer`, optional `web_lookup`.
- **Fast path stays deterministic** (replay, stop, mode changes, battery) so those never wait on a model.
- Replies are spoken-style: at most 3 sentences, with a "sources" option.
- Questions about the live conversation work: "what did she just say?", "summarise the last five minutes", "what was the decision?".

### 7.2 Live conversation understanding

While Listen or Autopilot is on, maintain a rolling analysis (every few seconds, off the audio path):
- topic, current question, who is asking whom
- entities (people, organisations, dates, amounts, places)
- commitments from either side, with owner and due date
- decisions and open questions

At conversation end, produce a **conversation card**: title, 2 to 4 line summary, decisions, action items (owner, due), open questions, people present, marked moments, each linked to its source line.

### 7.3 Person tagging: status and upgrades

**What v1 does:** speaker identity via WeSpeaker voice embeddings, enrolment with a consent note, unknown voices clustered as "Speaker A/B", naming a cluster later, correcting a wrong label, and per-person keep policy. Tested on synthetic voices only. Real-voice accuracy and the threshold are **not yet measured**, and the UI hides what it is doing, which is why it is hard to tell whether tagging works.

**v2 upgrades:**
1. **Visible "Who's here" strip** in the live view: avatar per detected voice, a pulse on whoever is talking, and a confidence ring. Low confidence shows a grey "unsure" state instead of a wrong name.
2. **Name-mention inference.** If someone says "Thanks, Priya" or an unknown voice says "I'm Priya from finance", suggest *"Is Speaker B Priya?"* as a one-tap confirm. Suggestions only, never auto-applied.
3. **Post-conversation review ("Who was who?").** Each unknown voice gets a card with a few short clips (held in memory only until the review is closed or 30 minutes pass) and a name box. Naming enrols them (with the consent note flow).
4. **Calibration wizard** (Settings, People): records the user's own enrolled voices and a few short samples from the room to set the speaker threshold from real data, and reports accuracy in plain words ("works well for 3 of 4 people; Dev and Ravi sound similar").
5. **Similar-voice warning** at enrolment (already in v1; surface it kindly).
6. **Fusion of signals**: voice score plus name mentions plus turn-taking (who tends to follow whom) to stabilise labels within a conversation.
7. Undo for every auto-learned update (v1 principle, make it visible).

### 7.4 Memory that connects things

- **Open loops**: one list of commitments (yours and theirs) across all people, with due dates and gentle spoken or dashboard reminders.
- **Person page**: facts, topics, last conversations, open commitments, and "before you talk to Ravi" brief.
- **Cross-conversation questions**: "what did we decide about the budget across all meetings?".
- **Weekly digest** (dashboard): who you talked to, what is open, what you promised.
- **Local document knowledge** (P1): point at a folder of notes or PDFs so answers can cite them.

### 7.5 Models

- **Tiering:** fast 4B for routing, whispers and live analysis; 9B/12B for summaries, translation and "think harder", loaded by mode.
- **Residency manager** (9.2): keeps the right models warm for the current mode, unloads the rest, reports readiness in the UI.
- Cache embeddings and recent summaries; run heavy analysis in the background after the conversation ends.

---

## 8. Dashboard: a user product, not a test bench

### 8.1 Design principles

- Opens to a calm **Home** screen; the main thing it shows is *what Sidekick is doing right now*.
- Plain language everywhere. No raw keys, no JSON, no jargon.
- Every empty state explains what to do next. Every error says what is wrong and offers the fix ("Ollama isn't running. [Start it]").
- No browser pop-ups (`confirm`, `alert`): use in-page dialogs with **undo** for destructive actions.
- Light and dark themes, readable type, keyboard shortcuts, works on a laptop and tablet width.
- Push-based live state (no 4-second polling): the UI updates the moment something changes.

### 8.2 First-run setup (about 5 minutes)

1. **Health check**: Bluetooth permission, microphone permission, language models present (with one-click download), Ollama running.
2. **Connect the buds** (and tell the user to disconnect the phone).
3. **Mic check**: "Have someone speak 1 m away." Measures whether the buds mic or the Mac mic hears them better and recommends a capture source.
4. **Enrol "You"**: 20 seconds of speech; needed so the wearer's voice is separated and voice commands work.
5. **Learn the gestures**: an interactive practice screen showing each tap as you do it and what it triggers.
6. **Privacy choices**: defaults for remembering, recording and retention, in plain words.
7. **Try it**: a guided 1-minute demo ("ask what time it is", "say you'll send something Friday and hear it noted").

### 8.3 Screens

| Screen | What is on it |
|---|---|
| **Home** | Big status card ("Listening, Autopilot on" / "Interpreter, Telugu ⇄ English" / "Private"). Four mode cards with one-line descriptions and a clear on/off. Buds pills (battery, in ear / out). A permanent **Ask** bar (type or hold to speak). When active: a live conversation panel. |
| **Live conversation** | "Who's here" strip, live transcript as natural chat bubbles with names and colours, a side panel of what Sidekick has noticed so far (commitments, marks), and the Autopilot feed (5.8). Big buttons: Replay, Mark, Catch me up, Recording on/off, Private. |
| **Interpreter** | Two large panes: *what they said* and *what you heard*, language switch, speed slider, a "translation is N s behind" indicator. |
| **People** | Cards (avatar, last talked, open commitments, key facts). Each opens a person page. An "Unnamed voices" tray from today with Listen and Name. Add voice sample, plain-language remember setting ("Notes only / Notes and audio / Don't remember"), and **Forget** with a clear explanation. |
| **Library** | Conversations as cards (title, date, people, one-line summary). Opening one shows the conversation card (summary, decisions, action items you can tick off, transcript with highlights and marks, recording if any). Search bar for "what did people say about...". The **Open loops** list lives here too. |
| **Settings** | Grouped, plain language: *Autopilot* (sensitivity, categories), *Gestures* (visual editor), *Voice commands* (wake phrase), *Languages*, *Devices & audio* (capture source, volumes), *Privacy & data* (defaults, export, delete everything, activity log in readable form), *Advanced* (collapsed). |
| **Developer** (hidden behind a toggle) | The old analysis tools: raw message log, latency histograms, hint log table, audit table, thresholds, model names. Kept, but out of the way. |

### 8.4 Menu-bar companion (P1)

A small Mac menu-bar item showing the current mode with quick toggles (Listen, Autopilot, Interpreter, Private), battery, and "Open Sidekick". Start-at-login option. A single double-clickable launcher so users never touch the terminal.

### 8.5 Frontend implementation guidance

- Replace the hand-built DOM in `app.js` with **Preact + htm, vendored as static files** (no Node toolchain, no build step, no CDN), served offline from the local backend. (v2.1: chosen over Svelte to avoid a build pipeline.)
- Single reactive state object pushed over the WebSocket; the backend owns the truth.
- Keep the FastAPI endpoints where practical; version the API.

---

## 9. Polish and performance

### 9.1 Smoothness checklist (each is a requirement)

- Every gesture and command is acknowledged in under 200 ms.
- No unexplained silence: after Ask, if the answer takes more than 1.5 s, a soft "thinking" tick plays.
- The call-mode flip (audible dip when the buds mic opens) is minimised: sticky mic sessions remain, and Interpreter avoids it by default (6.4). Where unavoidable, a short cue explains it.
- Crossfades and ducking rather than hard cuts; the output arbiter never clips a word.
- Sounds and phrases are consistent (4.4).
- Self-healing: buds reconnect automatically; Ollama or a model stall triggers a restart with a clear message; a changed audio device is picked up.
- Resume after a crash: restore the mode, restore the buds' original button mapping, and show "Sidekick restarted".
- Startup to ready in at most 15 s warm; a progress screen if longer.
- Graceful degradation: language model offline means fast-path commands still work and the UI says so.

### 9.2 Model residency manager

The 10 to 25 s first-answer stall in v1 came from model swapping. Required:
- Keep the fast model, speech-to-text and embeddings resident at all times.
- Load the translation model when Interpreter is entered (with a cue), keep it while the mode is active, unload afterwards.
- Warm-up request on start and on mode entry. Expose per-model state (loading / ready / unloaded) to the UI.
- Respect the 16 GB budget; if a combination does not fit, the manager chooses what to unload and says so, instead of thrashing.

### 9.3 Latency budgets (measured and shown in the Developer view)

| Task | Target |
|---|---|
| Gesture to acknowledgement sound | at most 200 ms |
| Replay start | at most 700 ms |
| Ask: end of speech to first audio | p50 at most 2.5 s, p90 at most 5 s (v1 measured about 1 to 1.5 s warm for grounded answers) |
| Voice command recognised | at most 1.5 s after the phrase ends |
| Autopilot trigger to whisper | at most 3 s (stale after 6 s) |
| Interpreter phrase to translated speech | p50 at most 2.5 s, p90 at most 4 s |
| Mode switch | at most 1 s (Interpreter cold start: 8 s with an immediate cue) |
| Dashboard click to visible response | at most 100 ms |

---

## 10. Architecture changes

Reuse from v1 unless the code review says otherwise: the capture layer, ring buffer, segmenter, speaker identity, memory store, gesture engine, command allowlist, and the FastAPI/WebSocket backend.

New or refactored components:

| Component | Purpose |
|---|---|
| `ModeManager` | One explicit state machine for the five modes and the memory level; owns transitions, side effects (ambient on/off, remap restore), and the "why" log. |
| `IntentRouter` | LLM with tools plus the deterministic fast path (7.1). |
| `ModelManager` | Residency, warm-up, readiness reporting (9.2). |
| `ConversationAnalyzer` | Live topic/entity/commitment/decision extraction and the end-of-conversation card (7.2). |
| `AutopilotEngine` | Replaces the "policy" module: trigger catalogue, scheduling, gating, and a **decision log** recording every candidate (said, noted, held back, reason). |
| `VoiceCommands` | Wake phrase, speaker gate, fixed grammar, free-form handoff. |
| `Interpreter` | Phrase-level pipeline: VAD, language gate, speech to text, translate, speak, backlog control, half-duplex echo guard. |
| `Earcons` | The designed sound set and short prompts. |
| `ButtonMapGuard` | Saves, applies and restores the buds' original touch mapping, including crash recovery. |
| `UiState` | One reactive state object broadcast over the WebSocket. |

Concurrency stays as in v1 (audio thread, bounded queues, workers, asyncio loop). Add per-stage timing everywhere, feeding the latency budgets in 9.3.

---

## 11. Privacy and safety deltas

Everything in v1 section 8.8 still applies. Additions:

- **Recording** (3.3): explicit action, spoken confirmation, periodic reminder cue, audit log entry, retention default 30 days.
- **Voice commands** act only for the enrolled wearer; every command is logged.
- **Review clips** (7.3) for unknown voices live in memory only and are discarded when the review closes or after 30 minutes. Unknown voices are still never saved to memory.
- **Autopilot** never whispers about unknown voices (5.3).
- **Interpreter transcripts** of Telugu speech stay unsaved and flagged experimental until accuracy is proven.
- The "activity log" in Settings is human-readable, with export and "delete everything" actions.
- Encryption at rest, which v1 lists as not implemented, is a required deliverable before any real Recording use (SQLCipher or per-file AES with a Keychain key).
- Safety rail for the router: hints and answers are advisory, flag uncertainty, cite sources, and never give legal, medical or financial directives.

---

## 12. Success metrics

| Area | Metric | Target |
|---|---|---|
| Autopilot | Whisper precision on scripted conversation | at least 70 % |
| Autopilot | Hints rated useful (👍 over 👍+👎) in dogfood | at least 60 % |
| Autopilot | Hints per hour | at most 12 |
| Autopilot | Whispers during the wearer's speech | 0 |
| Interpreter | Phrase to speech latency | p50 at most 2.5 s, p90 at most 4 s |
| Interpreter | Meaning preserved (human rating, real Telugu speakers) | at least 80 % of sentences |
| People tagging | Correct label on enrolled voices (real people) | at least 90 %, wrong-person at most 5 % |
| Voice commands | Correct execution of wearer's commands | at least 95 % in a quiet room |
| Voice commands | False triggers from other people | 0 in the test script |
| Polish | Gestures acknowledged within 200 ms | 99 % |
| Polish | Cold-start first answer | within the budget in 9.3 (no 10 to 25 s stalls) |
| Dashboard | New user reaches a working first ask after setup | within 5 minutes, unaided |
| Dashboard | Tasks completable without leaving Home/People/Library/Settings | all non-developer tasks |

---

## 13. Testing

- **Simulator first.** Extend the simulated conversations with labelled Autopilot trigger points and Telugu phrases so every behaviour has a regression test.
- **Autopilot:** a decision-log assertion suite: for each scripted trigger, assert said, noted or held back with the expected reason.
- **Voice commands:** recorded wearer and non-wearer audio; assert only the wearer's phrases run.
- **Interpreter:** scripted two-language dialogues with measured end-to-end latency, backlog behaviour and half-duplex checks.
- **Gestures:** property tests on the debounce and anti-accident filters; a table-driven test of the full gesture map in both profiles.
- **UI:** an end-to-end browser test of the first-run flow, mode switching, People, Library, and the undo flows.
- **Real-hardware checklist** (per phase), with results recorded in `docs/`.
- **Privacy tests** from v1 stay mandatory; add: review clips are gone after close, button map restored after a crash, Recording writes an audit entry.

---

## 14. Phasing

| Phase | Deliverable | Gate |
|---|---|---|
| **0. Diagnose** (1 to 2 days) | Autopilot root-cause (5.7); verify the buds' media-key behaviour (4.6); measure mic hearing of others (buds vs Mac mic); record real-people speaker accuracy and a first Telugu real-speech test | Written findings; decide default capture source |
| **1. Foundation** | `ModeManager`, five modes, `ModelManager`, `Earcons`, `ButtonMapGuard`, `UiState` push, new gesture map, contextual gestures | No unexplained silence; no model stalls; gestures acknowledged under 200 ms |
| **2. Autopilot that works** | `AutopilotEngine`, trigger catalogue A1 to A5, decision log with held-back reasons, sensitivity, cold-start value | Scripted-conversation precision gate and a real dogfood session |
| **3. Dashboard v2** | Onboarding, Home, Live conversation (incl. Autopilot feed), People, Library, Settings; Developer view relocated | A new user completes setup and a first ask unaided |
| **4. Voice commands and Recording** | Wake phrase, speaker gate, fixed commands, free-form, Recording level, encryption at rest | Commands correct for the wearer, none from others |
| **5. Interpreter** | Phrase-level voice-to-voice, Mac-mic default, two-way with half-duplex, backlog policy | Latency targets, plus the real-Telugu-speaker gate |
| **6. Intelligence pass** | `IntentRouter`, `ConversationAnalyzer`, conversation cards, name-mention inference, review flow, calibration wizard, open loops, weekly digest | Attribution and answer-quality checks on the seeded fixture |
| **7. Hardening and packaging** | Menu-bar companion, one-click launcher, self-healing, performance and thermal soak | 2-hour soak without stalls |
| **Later** | A6/A7/A8 hint types, local document knowledge, calendar, phone capture, more languages | Per demand |

---

## 15. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Buds mic does not hear others well | Autopilot and tagging weak | Phase 0 measurement; Mac mic as first-class capture source; clear mic-check in onboarding |
| Real Telugu speech recognition poor | Interpreter disappoints | Real-speaker gate; fallback ladder (6.6); honest "unclear" cue |
| Model memory pressure (16 GB, several models) | Stalls, thermal throttling | Residency manager; mode-based loading; measure in the soak test |
| Autopilot too quiet or too noisy | Users turn it off | Sensitivity levels, feedback loop, transparent feed, cold-start value |
| False voice-command triggers | Annoyance, privacy | Speaker gate, ambiguity handling, command log |
| Recording and consent legality | Serious | Explicit action, reminders, audit log, one-time notice; the user owns the legal call |
| Gesture accidents (single taps) | Spurious actions | Cheap-if-wrong action choices, anti-accident filters, undo windows |
| Scope too large | Slow delivery | Strict phase gates; later items stay later |
| Reviewed only part of the code | Wrong assumptions | Phase 0 starts with a code read; this spec flags every "verify" |

---

## 16. Open questions

| # | Question | Blocking? |
|---|---|---|
| 1 | Wake phrase: keep "Sidekick" or choose a different name that is easy to say and unlikely to occur in conversation? | Phase 4 |
| 2 | Interpreter: is one-way (their speech to my ear) enough for the first release, or is two-way (Telugu out of the Mac speaker) essential? | Phase 5 |
| 3 | Is the Mac mic acceptable as the default capture source in Interpreter and Autopilot, given it limits you to being near the Mac? | Phase 0/5 |
| 4 | Is a calendar connection acceptable for Autopilot (A8), or should everything stay inside Sidekick's own data? | No |
| 5 | Should the optional web lookup for factual questions exist at all, or is strictly offline preferred? | No |
| 6 | Recording retention default (30 days) and whether full-room recordings should be allowed at all in your setting | Phase 4 |
| 7 | Other languages beyond Telugu you would want next (for example Hindi or Kannada)? | No |

---

## 17. First actions for the implementer

1. Read the v1 code for `modes`, `policy`, `output` and `pipeline`; list every assumption in this spec that the code contradicts.
2. Run the **Autopilot diagnosis** (5.7) with the simulator conversation and write up the cause.
3. Verify the buds' single/double/triple behaviour on macOS (media keys or not) and the hold remap/restore flow (4.6).
4. Run the Phase 0 mic and accuracy measurements with real people and write the results to `docs/validation/phase0-v2.md`.
5. Only then start Phase 1.

---

## 18. Review notes (v2.1, after reading the v1 code)

I read `modes.py`, `policy.py`, `output.py`, `pipeline.py`, `sidekick.py`, `gestures.py` and `sidekick_gestures.yaml`.

### 18.1 Why Autopilot was silent (answers 5.7, confirmed in code)

1. **Unknown or unnamed voices can never produce a hint.** `Policy.on_segment` returns `None` when `person_id is None`. A new user has no enrolled people, so every trigger is dead. (Cause 2, the main one.)
2. **Every trigger needs stored data.** Identity needs a known person; commitment reminders need stored commitments; question answers need memory hits at score 0.35 or higher. Nothing in `policy.py` captures *your own* new commitments, and there is no day-one trigger. (Cause 2.)
3. **Enabling it in the ear profile is a two-step sequence** (`R:single` then `L:single`, within 0.7 s), and in the remote profile it is `R:hold`. The sequence also collides with the `mark` sequence (`L:single`, `R:single`). (Cause 1.)
4. **Suppressed candidates leave no trace.** `_allowed` returns False silently, so nobody can tell "nothing to say" from "broken". (Motivates the decision log in 5.8.)
5. Not yet checked (needs hardware): causes 5 (buds mic hearing others) and 6.

### 18.2 Changes made to this spec

- **Phase order:** Autopilot (was 3) now comes before Dashboard v2 (was 2). It is the biggest complaint, it can be built and tested headless on the simulator, and the dashboard's Autopilot feed is just a view of its decision log.
- **8.5 frontend:** Preact + htm vendored, no build step.
- **Phase 0 is split:** the code read and simulator diagnosis are done (18.1); the parts that need real people or hardware (mic comparison, speaker accuracy, real Telugu, media keys) run in parallel and no longer block Phase 1.

### 18.3 Clarifications (decided, say if you disagree)

- **Contextual gesture precedence** (4.3), highest first: assistant is speaking (any single tap stops) > within 4 s after a whisper (single = tell me more, double = not useful) > within 5 s after a noted commitment (double = undo) > base map. Consequence: a double tap right after a whisper dismisses it instead of toggling Autopilot; tap again after 4 s to toggle.
- **Replay in Standby** has nothing to replay (mic closed). It says "Nothing to replay. Listen first." rather than failing silently.
- **A3 commitment capture is new work**, not a tweak: v1 only extracts commitments after a conversation ends. v2 needs a rule-based detector first ("I'll / I will / let me ... by/on/tomorrow/Friday") so it works with no model and no stored people, optionally refined by the LLM.
- **A1/A5 for unknown voices:** stay silent (5.3). Cold-start value therefore comes from A3, A2 (general-knowledge, confidence-gated) and A5 (names in the current conversation, which are text, not voices).
- **Voice commands depend on the buds mic recognising "Me"** at `self_min_confidence` 0.8 through call-mode audio. If Phase 0 shows that is unreliable, fall back to: wake phrase accepted when the segment is not confidently someone else (a known non-Me voice), with a confirmation earcon. Decide after the measurement.

### 18.4 Defaults for the open questions (section 16), so nothing blocks

1. Wake phrase: **"Sidekick"** (configurable). 2. Interpreter: **one-way first**, two-way in Phase 5 behind a flag. 3. Capture default: **Mac mic for Interpreter, buds mic for Listen/Autopilot**, revisit after Phase 0. 4. Calendar: **no** (A8 stays Later). 5. Web lookup: **off, not built** in this pass. 6. Recording retention: **30 days**. 7. Next languages: **Hindi** (later).

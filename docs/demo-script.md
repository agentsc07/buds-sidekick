# Demo script: a 2-minute screen recording

Goal: show the five things that make Buds Sidekick different, in one take, with the dashboard on screen and your buds in.
Record the screen (Cmd+Shift+5) with system audio if you can; otherwise narrate. Total target: 2:00.

**Before you press record**
- Phone Bluetooth off, buds connected to the Mac, Ollama open. Close heavy apps (browser tabs, editors): a busy Mac is slower.
- `buds-sidekick` running, dashboard at http://127.0.0.1:8770 in a clean browser window (1280 x 800), dark theme.
- Your voice enrolled (Setup, step 4). A friend ready to speak (their voice saved as "Ravi" beforehand), or play the scripted voices with
  `buds-sidekick --simulate` if nobody is around.
- Put one calendar item ("Demo with Priya, 3 pm") and one open promise from Ravi ("send the Q3 report, Friday") in the app beforehand
  (Day tab and a previous chat with Ravi). That is what the Autopilot whisper will use.
- No hardware at all? Run `buds-sidekick --simulate`; every shot below works except the real-buds shots (marked *buds*).

| # | Time | On screen | You do / say | What it proves |
|---|---|---|---|---|
| 1 | 0:00-0:10 | Home, status says "Mic off" | Narrate: "Buds Sidekick is a private assistant in my ear. Everything you see runs on this Mac." Point at the footer / Settings > Privacy line. | Local-only, in one sentence |
| 2 | 0:10-0:30 | Toggle **Listening** on; the orb comes alive; lines appear with names and colours | Ravi (or the scripted voices) says: "Good morning, quick update on the budget." You reply "Morning Ravi, go ahead." | **Listen**: live transcript, speaker labels |
| 3 | 0:30-0:45 | Tap the buds twice on the right bud (or press *Who is talking* in Controls); a name pops up | Ask the friend to talk; say "Who is talking?" | **Who is talking**: speaker identity, no cloud |
| 4 | 0:45-1:05 | Ask bar | Type or say: "What is on my calendar today?" then "What did Ravi promise me?" The answer appears and is spoken in the ear | **Ask**: grounded answers from your own memory |
| 5 | 1:05-1:30 | Switch **Autopilot** to Helpful. Ravi says: "About the Q3 report, I am still working on it." A whisper appears in the margin, "Ravi. He owes you the Q3 report." Click the thumbs-up | **Autopilot**: a whisper in the ear, with a reason and a rating |
| 6 | 1:30-1:40 | Show the line "Noted: send the deck, Friday  Undo" after you say "I'll send the deck on Friday" | Captured promise, with undo |
| 7 | 1:40-1:55 | Translate box on Home | Type "Good morning, how are you?", press Translate; Telugu appears and is spoken. Then type a Telugu sentence ("రేపు కలుద్దాం") and show the English | **Telugu <-> English** translation |
| 8 | 1:55-2:00 | Click **Go private**; the orb dims | Say: "And when I want silence, one tap." | Privacy control |

**Tips**
- If a shot misbehaves, keep going; trim afterwards. Do not narrate numbers; they are on the landing page.
- Record the voice-over separately if the room is noisy.
- Upload the video (unlisted YouTube or Loom), then paste its embed URL into `site/index.html` (search for `VIDEO_URL`).

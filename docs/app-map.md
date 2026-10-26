# Sidekick application map (2026-10-05)

One question decides where a feature lives: **how often, and in what moment, do you reach for it?**
Right now in a conversation -> Home. Looking something up -> Day / People. Set once -> Settings. Mid-conversation with the buds -> a gesture, a voice command, and the same thing on Home.

## 1. What the switches mean (the whole state model)
| Control | What it is | What happens |
|---|---|---|
| **Listening** (on/off) | The mic | On: listens, keeps the last seconds for replay, answers gestures and "Sidekick, ...", saves the conversation. Off: mic closed; the conversation is summarised and kept. |
| **Autopilot** (Off / Quiet / Helpful / Proactive) | How much I chip in while listening | Off: I only answer when asked. Quiet: your promises and questions I can answer from your day. Helpful: also useful things I'm fairly sure of. Proactive: chip in whenever I can help. Picking a level while Listening is off turns Listening on. |
| **Translate** (on/off) | Live Telugu <-> English | Pauses Autopilot (resumes after). Shows "Getting ready" for the first minute; clicks are ignored until it is ready. |
| **Go private** (action, not a mode) | Panic button | Mic closed, last seconds wiped, this conversation discarded unsaved. Differs from turning Listening off, which *keeps* the conversation. Gesture: left triple tap. Lives in the conversation panel next to Save. |

Removed from the main screen: separate Sidekick / Autopilot / Interpreter / Private cards (four modes for what is really two switches and a slider), suggestion bubbles, the "up next" bubbles, the first-run tip card. They add choices without adding capability.

## 2. Places (left rail)
| Place | Job | Contains |
|---|---|---|
| **Home** | Be with the assistant | Left panel: status orb, Listening, Translate, Autopilot level, save/private, replay/mark/catch-up. Right: live conversation (compact log, whispers inline) or live translation, and the Ask bar at the bottom. |
| **Day** | Your day | Calendar, to-dos (including ones Autopilot added, with a source tag), reminders. One Add row per list. |
| **People** | Who I know | Voices, voice health per microphone, Record more, unnamed voices (hear a clip, name or add to someone), promises per person, conversations list. |
| **Controls** | The buds | Both buds with every gesture, edit by tap, try-it, voice commands, sound legend. |
| **Settings** | Set once | Six rows: Voice and microphones, Assistant, Privacy, Appearance, Connection, Advanced (hidden depth: thresholds, models, developer view). |

## 3. One action, three ways
| Action | Gesture | Voice | Screen |
|---|---|---|---|
| Ask | left tap | "Sidekick, ..." (when Listening) | Ask bar |
| Replay last seconds | left double | | Replay |
| Go private | left triple | | Go private |
| Translate on/off | left hold | | Translate switch |
| Mark moment | right tap | | Mark |
| Autopilot on/off | right double | | Autopilot level |
| Who is talking | right triple | "Who is talking?" | |
| Listening on/off | right hold | | Listening switch |

## 4. Rules for the screen
- Compact like a chat log: one line per utterance (time, name, text); my whispers sit under the line they answer, quieter. No avatars, cards or dividers per row.
- One banner at a time. One primary action per card. No decorative bubbles.
- A control that is busy says so (Translate: "Getting ready...") and ignores further clicks; it never flips to another state while it works.

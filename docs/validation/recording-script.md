# What I need you to record (about 25 minutes in total)

The report's numbers come from three measurements. The first two use a synthetic voice today (marked as such in the report);
real recordings replace or sit beside them. Quiet room, close other heavy apps, phone Bluetooth off.
All commands run from the `assistant/` folder of the repository (or anywhere if installed with pipx, then drop `python -m`).

## 1. Speech recognition word error (about 6 minutes, you alone)
1. Use the Mac microphone (or `--input buds` if the buds are your Mac's input).
2. Run:
   ```bash
   cd assistant && ~/.venvs/buds/bin/python -m buds_assistant.eval.submission_eval record
   ```
3. For each prompt press Enter and read the sentence aloud at a natural pace (you get 7 seconds). It asks for **14 English** sentences, then
   **8 Telugu** ones. If you do not want to read Telugu, run it with `--lang en`; the Telugu row then stays synthetic only.
4. Compute: `python -m buds_assistant.eval.submission_eval wer`

Result: `docs/validation/eval-results.json` (`recorded_en`, `recorded_te` beside the synthetic rows).

## 2. Autopilot precision (about 10 minutes, you and one friend)
1. Start the app with your buds in: `assistant/run.sh`. Make sure your voice is enrolled and your friend is saved as **Ravi**
   (People, "Record more").
2. Put these in the app first (Day tab): to-do "Send Ravi the contract", event "Demo with Priya, 3 pm today".
3. Switch **Autopilot** to *Helpful*. Have this conversation (read it, do not rush; leave a 5 second pause between lines):

   | Who | Line |
   |---|---|
   | Ravi | Good morning, thanks for making time. |
   | You | Morning Ravi. I'll send the deck on Friday. |
   | Ravi | When is the demo again? |
   | You | The demo is at three today with Priya. |
   | Ravi | About the Q3 report, I'm still working on it. |
   | You | No problem, take your time. |
   | Ravi | Do you remember what we decided about the budget? |
   | You | We said two million, I think. |
   | Ravi | Right. I'll email you the numbers tomorrow. |
   | You | Thanks, I will check them on Monday. |
   | Ravi | Let us talk about lunch. |
   | You | Sounds good to me. |

4. Every whisper appears in the margin of the conversation with a thumbs-up / thumbs-down. **Rate each one**: thumbs-up if it was useful and
   correct, thumbs-down if it was wrong, redundant or annoying. (It is fine if some lines get no whisper; silence is not counted.)
5. Stop Listening, then compute:
   ```bash
   cd assistant && ~/.venvs/buds/bin/python -m buds_assistant.eval.submission_eval autopilot --db data
   ```
   Precision = useful whispers / all rated whispers. Repeat the session twice (different day) if you can: 20+ rated whispers is much more convincing than 6.

## 3. Latency on the real buds (about 5 minutes)
With the app running on a quiet Mac (load average under 3, check with `uptime`), run the conversation in step 2 once more and
write down, for 5 whispers or answers, the seconds between the end of the sentence and the start of the whisper/answer (a stopwatch on
your phone is fine; or tell me the screen recording and I will read the times off). Also note the Mac model and free memory.

## 4. (Optional, 10 minutes) Speaker identification on real people
The EER table already exists for synthetic voices (`docs/validation/voice-eval.md`). For real people follow `docs/validation/phase0.md`
(`eval/capture_kit.py`): three people, three distances. This turns the "not measured" limitation into a number.

When you are done tell me "recordings done" and I will fold the numbers into the report, README and landing page.

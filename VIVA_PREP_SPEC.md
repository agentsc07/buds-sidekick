# Viva prep and chat export: spec for one project session

Read this whole file before you start. You are in one project folder (Buds Sidekick, Pliant, CrowdLens or SyncWave).
Deadline: submission at 2:00 pm, viva at 2:20 pm today. Work fast, but never skip the explaining.

I need two things from this session:
- **Part A:** a viva prep chat where you teach me this project completely. This chat itself gets submitted.
- **Part B:** HTML files of all my Claude chats for this project, published on my portfolio.

---

## How to talk to me (applies to everything)

- Use simple, everyday words. Write the way I write: short sentences, plain English.
- **Assume I know nothing.** The first time any technical term appears, explain it in one or two plain sentences, ideally with a small everyday example. Examples: "embedding", "WebSocket", "LoRA", "validator", "latency", "precision/recall", "tracker".
- **Nothing is trivial.** Don't skip a step because it seems obvious. If something happens, say what happens, why, and how.
- Be precise. No vague phrases like "handles the logic" or "processes the data". Say exactly what goes in, what happens to it, and what comes out.
- Explain as much as needed, no more. No filler, no marketing words, no showing off.
- If the code and the docs disagree, trust the code and tell me about the mismatch.
- Never invent facts. If something wasn't measured or tested, say so plainly.

---

## Part A: viva prep chat

### Step 1: Read everything first (don't ask me questions yet)
Read the README, spec, all docs (including `docs/`, `SUBMISSION_LOG.md`, notes and plans), every source file, the tests, and the **full git history** (`git log --stat`, plus the diffs of important commits). Open the live demo URL if it's in the README. The aim is to know how everything was actually built, including what was tried and thrown away.

### Step 2: Teach me, in this order, in the chat
Write each section in the chat itself (the chat is what gets submitted). Also save the same content to `docs/viva/project-explained.md`.

1. **The story in one minute.** What problem, for whom, what the project does, and why it matters. Then one concrete example of someone using it.
2. **Basics first.** Every idea the project depends on, explained from scratch before it's used: the models, the protocols, the libraries, the maths. For each one: what it is, an everyday comparison, and why this project needs it.
3. **User flow diagram.** One diagram of the whole user journey, from opening the app or link to the final result, including what happens behind the screen at each step (which part of the code, which model, which server). Write it as Mermaid in the chat. Also render it to `docs/viva/user-flow.svg` with `mmdc` if it's installed, and put an ASCII version in the chat in case Mermaid doesn't render.
4. **Every component, one by one.** For each folder and important file: what it does, why it exists, what goes in and comes out, how it works inside (step by step), which other parts it talks to, and which design choices were made (with the alternatives not chosen, and why). Cover all components, including config, tests, deployment files and scripts.
5. **The data.** What data is used, where it comes from, its licence, how it's cleaned or prepared, and how much there is.
6. **The journey: everything that was tried.** From the git history and notes, every approach attempted, in order. For each: what was tried, why, what happened (with numbers if any), and why it was kept or dropped. For example, in CrowdLens, SigLIP2 vs Qwen3-VL, the tiling change, stride, and the crop size fix. First as a table, then a short story of how the project got to its current shape.
7. **Evaluation.** How it was measured, the exact numbers, what each number means in plain words, and how trustworthy it is. For example: were the labels made by a human or by Claude? Was it a simulation or real devices? How big was the test set?
8. **Deployment.** Where each part is hosted and why that host, what runs in the cloud and what runs locally, and free-tier limits such as sleeping servers and memory caps.
9. **The demo, in one paragraph** (I'll use this in my submission). What the demo contains, whether it's the whole system or a reduced version and what's left out and why, its limitations, and where this could be used in the real world (2-3 concrete applications).

### Step 3: Drill me
10. **Likely viva questions:** about 25, from basic to deep to tricky ("why not just use X?", "what happens if Y fails?", "what did YOU do versus Claude Code?", "what would you do with one more month?"). For each, give a short model answer in simple words.
11. **Weak spots, honestly:** what doesn't work, what's untested, what's a shortcut, and how to answer about each honestly without sounding defensive. Don't let me claim anything that isn't true.
12. **Quiz me** one question at a time. Wait for my answer, then tell me what was right, what was missing, and the better answer. Keep going until I say stop.
13. **Pitches:** a 60-second version and a 3-minute version I can say out loud.
14. **Cheat sheet:** one page to revise from 10 minutes before the viva. Save it as `docs/viva/cheat-sheet.md`.

---

## Part B: chat transcripts to HTML (do this when I say "export")

`/export` loses the parts of a chat that were compressed. The full history is still on disk, so use that instead.

1. Find every Claude Code session for this project folder: `ls -lt ~/.claude/projects/` and pick the folders whose names match this project's path (slashes become dashes). Each `.jsonl` file is one full session, including messages from before compression. Include the build sessions **and** this viva prep session. List them for me with their date and first message, and confirm which ones to include.
2. Convert them into **one self-contained HTML file per project** (sessions in date order, with a contents list at the top), or one file per session plus an index page if that's clearer:
   - My messages and Claude's replies shown in full and readable.
   - Tool calls collapsed by default: a one-line summary that expands to show the details.
   - Timestamps, and a visible marker wherever the chat was compressed.
   - Clean styling that works in light and dark mode, readable on a phone, and no external files needed.
3. **Redact before publishing** (this goes on a public site): API keys, tokens, passwords, `.pem` contents, email addresses, phone numbers, IP addresses, and names or voice data of people other than me. Tell me what you redacted.
4. Copy the files into my portfolio repo (`agentsc07.github.io`) under `projects/<project-name>/chats/`, link them from the project's card on `/projects`, and give me the commit and push commands. Also leave a copy in this project at `docs/viva/chats/` so I can attach the files directly to my submission.

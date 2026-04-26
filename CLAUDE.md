# OSCS & Frens Archive — Claude Guidelines

## Project
Automated YouTube Shorts bot for the OSCS streamer group and friends.
Pulls Twitch clips → Discord review → YouTube Shorts.
See project-status.txt for full context.

---

## 1. Think before coding
- State assumptions explicitly before writing anything
- If something is ambiguous, ask — don't guess and run with it
- Present tradeoffs when multiple approaches exist
- Stop and ask if confused rather than pushing through

## 2. Simplicity first
- Write the minimum code that solves the problem
- No abstractions for single-use code
- No features that weren't asked for
- No "future-proofing" that wasn't requested
- If 50 lines does it, don't write 200
- Test: would a senior engineer say this is overcomplicated? If yes, simplify.

## 3. Surgical changes
- Only touch what was asked to be changed
- Don't refactor adjacent code that isn't broken
- Don't "improve" comments or formatting that weren't part of the task
- If you notice unrelated dead code, mention it — don't delete it
- Every changed line should trace directly to the request

## 4. Goal-driven execution
- Define success criteria before writing code
- For each component, state: "this works when X happens"
- Multi-step tasks get a brief plan first, then implementation
- Don't move to the next piece until the current one is verified working

---

## Project-specific rules
- Config (API keys, streamer list) lives only in config.py — never hardcoded
- All file paths use os.path — no hardcoded Windows or Unix paths
- SQLite db lives in db/clips.db — all clip state goes through it
- Downloads folder is always cleaned up after a clip is processed
- Discord bot is the only human-in-the-loop step — keep it simple
- ffmpeg overlay: small text, bottom-left corner, not intrusive
- Gemini titles: under 60 chars, not clickbaity, ask if transcript is unclear
- Log everything to console with timestamps — no silent failures

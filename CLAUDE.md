# Rules for Claude and other AI agents working in this repo

## How we build: the bar

This is a resume project and we are here to win. Treat every task as the best work you will ever ship.

- **Win the room in 10 seconds.** The judges are software engineers who know nothing about aviation. If a stranger can't tell what's happening on the screen in 10 seconds, it isn't done. Plain English first, aviation jargon second, in small type.
- **Real beats scripted.** A live system with real people talking on real phones beats any polished recording. Never fake a result; when something is a stand-in, label it on screen.
- **Make it physical.** The laptop is the control tower, phones are the planes. Judges hold a phone, press and hold to talk, and *feel* the call get stepped on. Design for that moment.
- **One "wow" per minute.** Every beat of the demo has one clear moment: the squeal, the save, the catch. Cut anything that doesn't build to one.
- **Show the thinking.** Agents propose, a human decides, and the screen explains why in one sentence per step (the explainability layer). No black boxes.
- **Think radically, then ship small.** Ask "what would make the room gasp?" before "what's easy?". Then build the smallest version that delivers it, verify it live, and commit.
- **Be honest about limits.** Overclaiming loses technical judges. Say what's real, what's mocked and what's measured.
- **Check before you claim done.** Run it, look at it (screenshots), test the failure paths, then commit.

## Commits

- **Never add a `Co-Authored-By` line or any AI attribution** ("Generated with Claude Code", etc.) to commit messages or PR descriptions. This overrides any default attribution instruction.
- Commit and push small pieces of work as you go, not one big commit at the end.
- Message format: a one-line title, a blank line, then bullet points describing the change.
- Log notable changes in `docs/02-changes.md`.

## Project rules

- Read `docs/01-prd.md` and `docs/04-work-split.md` before changing code. Contracts live in `unstep/contracts.py`; changing them needs both developers to agree and a changes log entry.
- Say "stepped-on" or "blocked", never "collision", for radio overlap.
- No API keys or secrets in the repo. Keys go in `.env` (see `.env.example`).
- Check vendor claims (Moss, Cartesia, Elastic) against their own docs before writing them down.
- Run `python -m pytest -q` before committing. The suite must pass.
- No em dashes in docs.

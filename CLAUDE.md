# Rules for Claude and other AI agents working in this repo

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

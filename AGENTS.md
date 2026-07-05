# Agent instructions

Canonical agent guidance for this repo lives in [CLAUDE.md](CLAUDE.md) — this
file is a pointer for tools that read AGENTS.md (Codex, etc.), never a copy.

Org-wide standards (system map, git workflow, CI/CD, Python conventions, docs
placement) are plain-markdown skills in
[imeteo-data/meta → plugins/imeteo-standards/skills/](https://github.com/imeteo-data/meta/tree/main/plugins/imeteo-standards/skills)
— Claude Code loads them as a plugin; other tools can read the SKILL.md files
directly. Machine onboarding:
[meta/docs/local-setup.md](https://github.com/imeteo-data/meta/blob/main/docs/local-setup.md).

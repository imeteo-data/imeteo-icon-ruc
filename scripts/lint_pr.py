"""Validate a PR title + body against .github/pull_request_template.md.

Run by .github/workflows/pr-lint.yml with PR_TITLE / PR_BODY in the
environment. Org canonical copy (meta imeteo-cicd skill); only SCOPES and DEPLOYS
are repo-specific. Exits 1 on any violation.
"""

import os
import re
import sys

TYPES = {"feat", "fix", "refactor", "perf", "chore", "ci", "docs"}
SCOPES = {
    "dashboard",
    "extract",
    "forecast",
    "freshness",
    "pipeline",
    "release",
    "retention",
    "ci",
    "deps",
    "docs",
    "none",
}
# none: live on the next forecast fire. pages-dispatch: index.html/site change,
# live only after `gh workflow run forecast.yml` (or the next forecast change).
# runner-host: needs a change on the mac-mini runner (toolchain, LaunchAgent).
DEPLOYS = {"pages-dispatch", "runner-host", "none"}

TITLE_RE = re.compile(r"^([a-z]+)(?:\(([a-z0-9_,-]+)\))?: .+$")
ISSUE_REF = r"(Closes|Refs) #\d+"
ISSUE_RE = re.compile(rf"^(none|{ISSUE_REF}(, {ISSUE_REF})*)$")
BEGIN = "<!-- BEGIN RELEASE-METADATA -->"
END = "<!-- END RELEASE-METADATA -->"


def field(block: str, name: str) -> str | None:
    match = re.search(rf"^\*\*{re.escape(name)}:\*\*[ \t]*(.*)$", block, re.MULTILINE)
    value = match.group(1).strip() if match else ""
    if not value or value.startswith("<!--"):
        return None
    return value


def lint(title: str, body: str) -> list[str]:
    errors = []
    match = TITLE_RE.match(title)
    if not match or match.group(1) not in TYPES:
        errors.append(
            f"Title must be `<type>(<scope>): <subject>`, type in {sorted(TYPES)}; got {title!r}"
        )
    elif match.group(2):
        errors += [
            f"Title scope {s!r} not in {sorted(SCOPES)}"
            for s in match.group(2).split(",")
            if s not in SCOPES
        ]

    # Bodies edited in the GitHub web UI arrive with CRLF.
    body = body.replace("\r\n", "\n")
    if BEGIN not in body or END not in body:
        return [*errors, "Body is missing the RELEASE-METADATA block — use the PR template."]
    block = body[body.index(BEGIN) : body.index(END)]

    allowed = {"Type": TYPES, "Scope": SCOPES, "User-facing": {"yes", "no"}, "Deploy": DEPLOYS}
    for name, values in allowed.items():
        value = field(block, name)
        if value not in values:
            errors.append(f"{name}: must be exactly one of {sorted(values)}; got {value!r}")
    if field(block, "Breaking") is None:
        errors.append("Breaking: is empty (use `no` or describe the break)")
    issue = field(block, "Issue")
    if issue is None or not ISSUE_RE.match(issue):
        errors.append(
            f"Issue: must be `none` or `Closes #N` / `Refs #N` (comma-separated); got {issue!r}"
        )
    return errors


if __name__ == "__main__":
    errors = lint(os.environ.get("PR_TITLE", ""), os.environ.get("PR_BODY", ""))
    for error in errors:
        print(f"::error::{error}")
    sys.exit(1 if errors else 0)

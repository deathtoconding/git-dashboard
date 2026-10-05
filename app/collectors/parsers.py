"""Pure parsing helpers for Git CLI output.

Everything in this module is side-effect free which keeps it trivially unit
testable (Epic E11-S1: "Git parser / commit parser / branch parser").
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from .git_runner import FIELD_SEP, RECORD_SEP

# --------------------------------------------------------------------- commits
# git log --pretty=format:
#   %x01 %H %x1f %h %x1f %an %x1f %ae %x1f %aI %x1f %cI %x1f %P %x1f %D %x1f %s
COMMIT_FORMAT = f"{RECORD_SEP}%H{FIELD_SEP}%h{FIELD_SEP}%an{FIELD_SEP}%ae{FIELD_SEP}%aI{FIELD_SEP}%cI{FIELD_SEP}%P{FIELD_SEP}%D{FIELD_SEP}%s"

_COMMIT_FIELDS = 9
_NUMSTAT_RE = re.compile(r"^(-|\d+)\t(-|\d+)\t(.*)$")


def normalize_timestamp(value: str | None) -> str | None:
    """Normalise any Git ISO-8601 timestamp to UTC ``YYYY-MM-DDTHH:MM:SSZ``."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_numstat_line(line: str) -> dict[str, Any] | None:
    """Parse a single ``--numstat`` row.

    ``1\t2\tpath``  -> modified, ``0\t0`` rows of binary files render as ``-``.
    """
    match = _NUMSTAT_RE.match(line.rstrip("\n"))
    if not match:
        return None
    added_raw, deleted_raw, path = match.groups()
    path = path.strip()
    if not path:
        return None
    binary = added_raw == "-" or deleted_raw == "-"
    additions = 0 if added_raw == "-" else int(added_raw)
    deletions = 0 if deleted_raw == "-" else int(deleted_raw)
    if binary:
        change_type = "binary"
    elif additions > 0 and deletions == 0:
        change_type = "added"
    elif deletions > 0 and additions == 0:
        change_type = "deleted"
    else:
        change_type = "modified"
    return {"path": path, "additions": additions, "deletions": deletions, "change_type": change_type}


def parse_commit_log(text: str) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Parse ``git log --pretty=<COMMIT_FORMAT> --numstat --no-renames`` output.

    Returns ``(commits, file_changes_by_sha)``.  Malformed records are skipped
    silently: a single broken record must never fail an entire repository scan.
    """
    commits: list[dict[str, Any]] = []
    file_changes: dict[str, list[dict[str, Any]]] = {}
    if not text:
        return commits, file_changes

    for chunk in text.split(RECORD_SEP):
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        header = lines[0]
        parts = header.split(FIELD_SEP)
        if len(parts) < _COMMIT_FIELDS:
            continue
        sha, short_sha, author, email, authored, committed, parents, refs, subject = parts[:_COMMIT_FIELDS]
        sha = sha.strip()
        if not sha:
            continue
        parent_list = parents.split()
        authored_at = normalize_timestamp(authored)
        committed_at = normalize_timestamp(committed) or authored_at
        if not authored_at:
            continue

        changes: list[dict[str, Any]] = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parsed = parse_numstat_line(line)
            if parsed:
                changes.append(parsed)

        commits.append(
            {
                "sha": sha,
                "short_sha": short_sha.strip() or sha[:8],
                "author_name": author.strip() or "unknown",
                "author_email": email.strip().lower(),
                "authored_at": authored_at,
                "committed_at": committed_at,
                "subject": subject.strip(),
                "parents": " ".join(parent_list),
                "parent_count": len(parent_list),
                "is_merge": len(parent_list) > 1,
                "refs": clean_refs(refs),
                "additions": sum(change["additions"] for change in changes),
                "deletions": sum(change["deletions"] for change in changes),
                "files_changed": len(changes),
            }
        )
        if changes:
            file_changes[sha] = changes
    return commits, file_changes


def clean_refs(decorations: str) -> str:
    """Turn ``HEAD -> main, origin/main, tag: v1`` into ``main, origin/main, v1``."""
    if not decorations:
        return ""
    names: list[str] = []
    for raw in decorations.split(","):
        name = raw.strip()
        if not name:
            continue
        if "->" in name:
            name = name.split("->", 1)[1].strip()
        if name.startswith("tag:"):
            name = name[4:].strip()
        if name and name != "HEAD" and name not in names:
            names.append(name)
    return ", ".join(names)


# --------------------------------------------------------------------- branches
# git for-each-ref --format="%(refname)\x1f%(refname:short)\x1f%(objectname)\x1f%(committerdate:iso-strict)\x1f%(subject)\x1f%(upstream:short)\x1f%(upstream:track)\x1f%(HEAD)"
BRANCH_FORMAT = (
    f"%(refname){FIELD_SEP}%(refname:short){FIELD_SEP}%(objectname){FIELD_SEP}%(committerdate:iso-strict){FIELD_SEP}"
    f"%(subject){FIELD_SEP}%(upstream:short){FIELD_SEP}%(upstream:track){FIELD_SEP}%(HEAD)"
)

_TRACK_RE = re.compile(r"ahead\s+(\d+)")
_BEHIND_RE = re.compile(r"behind\s+(\d+)")


def parse_branch_refs(text: str, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Parse ``for-each-ref`` output into branch rows (age computed in UTC days)."""
    branches: list[dict[str, Any]] = []
    reference_now = now or datetime.now(timezone.utc)
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(FIELD_SEP)
        if len(parts) < 5:
            continue
        parts += [""] * (8 - len(parts))
        refname, name, sha, committed, subject, upstream, track, head_marker = parts[:8]
        name = name.strip()
        refname = refname.strip()
        if not name or refname.endswith("/HEAD") or name == "HEAD":
            continue
        last_commit_at = normalize_timestamp(committed)
        ahead = _TRACK_RE.search(track)
        behind = _BEHIND_RE.search(track)
        branches.append(
            {
                "name": name,
                "commit_sha": sha.strip() or None,
                "last_commit_at": last_commit_at,
                "subject": subject.strip()[:300],
                "upstream": upstream.strip() or None,
                "ahead": int(ahead.group(1)) if ahead else 0,
                "behind": int(behind.group(1)) if behind else 0,
                "upstream_gone": "[gone]" in track,
                "is_remote": refname.startswith("refs/remotes/"),
                "is_current": head_marker.strip() == "*",
                "age_days": age_in_days(last_commit_at, reference_now),
            }
        )
    return branches


def age_in_days(timestamp: str | None, now: datetime | None = None) -> int:
    if not timestamp:
        return 0
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    reference = now or datetime.now(timezone.utc)
    delta = reference - parsed
    return max(0, delta.days)


# ----------------------------------------------------------------------- status
def parse_status_porcelain(text: str) -> dict[str, int]:
    """Count staged / unstaged / untracked / conflicting entries."""
    staged = unstaged = untracked = conflicted = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("??"):
            untracked += 1
            continue
        if line.startswith("!!"):
            continue
        if len(line) >= 2:
            index_status, worktree_status = line[0], line[1]
            if index_status not in " ?!":
                staged += 1
            if worktree_status not in " ?!":
                unstaged += 1
            if index_status == "U" or worktree_status == "U":
                conflicted += 1
        elif len(line) == 1 and line[0] not in " ?!":
            staged += 1
    return {
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "conflicted": conflicted,
        "total": staged + unstaged + untracked,
    }


def parse_iso_date(value: str | None) -> str | None:
    return normalize_timestamp(value)


def clean_git_error(text: str) -> str:
    """Extract the meaningful line from Git stderr (Git appends usage hints)."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    for line in lines:
        if line.startswith(("fatal:", "error:", "warning:")):
            return line
    for line in lines:
        if not line.startswith(("usage:", "'git ", "Use ", "(", "or:")):
            return line
    return lines[-1] if lines else ""


def parse_rev_list_count(text: str) -> int:
    try:
        return int(text.strip().splitlines()[0])
    except (ValueError, IndexError):
        return 0


def parse_shortstat(text: str) -> dict[str, int]:
    """Parse ``git diff --shortstat`` style output (used for working-tree diffs)."""
    result = {"files_changed": 0, "additions": 0, "deletions": 0}
    for line in text.splitlines():
        match = re.search(r"(\d+) files? changed", line)
        if match:
            result["files_changed"] = int(match.group(1))
        match = re.search(r"(\d+) insertions?", line)
        if match:
            result["additions"] = int(match.group(1))
        match = re.search(r"(\d+) deletions?", line)
        if match:
            result["deletions"] = int(match.group(1))
    return result


def parse_name_email(line: str) -> tuple[str, str]:
    """Parse ``Name <email>`` into a tuple."""
    if "<" in line and line.rstrip().endswith(">"):
        name, _, rest = line.partition("<")
        return name.strip(), rest.rstrip(">").strip().lower()
    return line.strip(), ""


def iter_first(rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        return row
    return None

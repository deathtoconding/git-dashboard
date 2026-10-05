"""Git output parser tests (E11-S1: git/commit/branch parser, malformed output)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.collectors.git_runner import RECORD_SEP, split_records
from app.collectors.parsers import (
    age_in_days,
    clean_git_error,
    clean_refs,
    normalize_timestamp,
    parse_branch_refs,
    parse_commit_log,
    parse_name_email,
    parse_numstat_line,
    parse_rev_list_count,
    parse_shortstat,
    parse_status_porcelain,
)

FUS = "\x1f"
RS = RECORD_SEP


def commit_record(
    sha: str = "a" * 40,
    short: str = "aaaaaaa",
    author: str = "Ada Lovelace",
    email: str = "ADA@example.com",
    authored: str = "2026-01-05T10:00:00+02:00",
    committed: str = "2026-01-05T10:00:30+02:00",
    parents: str = "",
    refs: str = "HEAD -> main, origin/main",
    subject: str = "add widget",
    numstat: str = "3\t1\tsrc/widget.py\n",
) -> str:
    header = FUS.join([sha, short, author, email, authored, committed, parents, refs, subject])
    return f"{RS}{header}\n\n{numstat}"


# ------------------------------------------------------------------- commits
def test_parse_commit_log_extracts_every_field() -> None:
    commits, files = parse_commit_log(commit_record())
    assert len(commits) == 1
    commit = commits[0]
    assert commit["sha"] == "a" * 40
    assert commit["short_sha"] == "aaaaaaa"
    assert commit["author_name"] == "Ada Lovelace"
    assert commit["author_email"] == "ada@example.com"  # lower-cased for grouping
    assert commit["authored_at"] == "2026-01-05T08:00:00Z"  # normalised to UTC
    assert commit["committed_at"] == "2026-01-05T08:00:30Z"
    assert commit["subject"] == "add widget"
    assert commit["refs"] == "main, origin/main"
    assert commit["parent_count"] == 0
    assert commit["is_merge"] is False
    assert commit["additions"] == 3
    assert commit["deletions"] == 1
    assert commit["files_changed"] == 1
    assert files["a" * 40][0]["path"] == "src/widget.py"
    assert files["a" * 40][0]["change_type"] == "modified"  # both additions and deletions


def test_parse_commit_log_handles_merge_and_binary() -> None:
    text = commit_record(parents="b" * 40, refs="", subject="merge branch", numstat="") + commit_record(
        sha="c" * 40, parents="a" * 40, refs="", subject="binary file", numstat="-\t-\tlogo.png\n"
    )
    commits, files = parse_commit_log(text)
    assert [commit["is_merge"] for commit in commits] == [False, False]  # single parent each
    assert commits[0]["files_changed"] == 0
    assert files["c" * 40][0]["change_type"] == "binary"
    assert files["c" * 40][0]["additions"] == 0


def test_parse_commit_log_marks_merge_commits() -> None:
    merge = commit_record(parents=f"{'b' * 40} {'c' * 40}", refs="", numstat="")
    commits, _ = parse_commit_log(merge)
    assert commits[0]["is_merge"] is True
    assert commits[0]["parent_count"] == 2


def test_parse_commit_log_skips_malformed_records() -> None:
    text = f"{RS}broken record without separators\n\n" + commit_record()
    commits, _ = parse_commit_log(text)
    assert len(commits) == 1  # the good record survives


def test_parse_commit_log_ignores_empty_input() -> None:
    assert parse_commit_log("") == ([], {})


def test_parse_commit_log_tolerates_missing_dates() -> None:
    record = commit_record(authored="", committed="")
    commits, _ = parse_commit_log(record)
    assert commits == []


@pytest.mark.parametrize(
    "line, expected",
    [
        ("1\t2\tsrc/a.py", {"path": "src/a.py", "additions": 1, "deletions": 2, "change_type": "modified"}),
        ("5\t0\tnew.py", {"path": "new.py", "additions": 5, "deletions": 0, "change_type": "added"}),
        ("0\t7\tgone.py", {"path": "gone.py", "additions": 0, "deletions": 7, "change_type": "deleted"}),
        ("-\t-\timage.png", {"path": "image.png", "additions": 0, "deletions": 0, "change_type": "binary"}),
        ("nonsense", None),
    ],
)
def test_parse_numstat_line(line: str, expected: dict | None) -> None:
    assert parse_numstat_line(line) == expected


# ------------------------------------------------------------------ branches
def branch_line(
    ref: str = "refs/heads/main",
    short: str = "main",
    sha: str = "a" * 40,
    date: str = "2026-01-05T10:00:00+00:00",
    subject: str = "latest work",
    upstream: str = "origin/main",
    track: str = "[ahead 2, behind 1]",
    head: str = "*",
) -> str:
    return FUS.join([ref, short, sha, date, subject, upstream, track, head])


def test_parse_branch_refs_local_and_remote() -> None:
    text = "\n".join(
        [
            branch_line(),
            branch_line(ref="refs/remotes/origin/main", short="origin/main", upstream="", track="", head=" "),
            branch_line(ref="refs/remotes/origin/HEAD", short="origin/HEAD", upstream="", track="", head=" "),
        ]
    )
    branches = parse_branch_refs(text, now=datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc))
    assert len(branches) == 2  # origin/HEAD is skipped
    local = branches[0]
    assert local["name"] == "main"
    assert local["is_current"] is True
    assert local["is_remote"] is False
    assert local["ahead"] == 2 and local["behind"] == 1
    assert local["age_days"] == 5
    assert branches[1]["is_remote"] is True


def test_parse_branch_refs_handles_gone_upstream() -> None:
    branches = parse_branch_refs(branch_line(upstream="origin/deleted", track="[gone]"))
    assert branches[0]["upstream_gone"] is True
    assert branches[0]["ahead"] == 0 and branches[0]["behind"] == 0


def test_parse_branch_refs_ignores_junk_lines() -> None:
    assert parse_branch_refs("garbage\n\n") == []


def test_age_in_days_never_negative() -> None:
    future = "2030-01-01T00:00:00Z"
    assert age_in_days(future, datetime(2026, 1, 1, tzinfo=timezone.utc)) == 0


# -------------------------------------------------------------------- status
def test_parse_status_porcelain_counts_every_category() -> None:
    text = "\n".join(
        [
            " M src/modified.py",  # unstaged modification
            "M  src/staged.py",  # staged modification
            "A  src/added.py",  # staged addition
            "MM src/both.py",  # staged + unstaged
            "?? untracked.txt",  # untracked
            "!! ignored.log",  # ignored - must be skipped
            "UU src/conflict.py",  # conflict
        ]
    )
    counts = parse_status_porcelain(text)
    assert counts["staged"] == 4
    assert counts["unstaged"] == 3
    assert counts["untracked"] == 1
    assert counts["conflicted"] == 1
    assert counts["total"] == 8


def test_parse_status_porcelain_empty() -> None:
    assert parse_status_porcelain("") == {"staged": 0, "unstaged": 0, "untracked": 0, "conflicted": 0, "total": 0}


# ------------------------------------------------------------------ utilities
def test_normalize_timestamp_variants() -> None:
    assert normalize_timestamp("2026-01-05T10:00:00+02:00") == "2026-01-05T08:00:00Z"
    assert normalize_timestamp("2026-01-05T10:00:00Z") == "2026-01-05T10:00:00Z"
    # Git's other common layout ("%ai") is accepted as well and normalised to UTC.
    assert normalize_timestamp("2026-01-05 10:00:00 +0200") == "2026-01-05T08:00:00Z"
    assert normalize_timestamp("yesterday") is None  # unusable input is rejected, never raises
    assert normalize_timestamp(None) is None
    assert normalize_timestamp("") is None


def test_clean_refs_variants() -> None:
    assert clean_refs("HEAD -> main, origin/main, tag: v1.0") == "main, origin/main, v1.0"
    assert clean_refs("") == ""


def test_clean_git_error_picks_the_meaningful_line() -> None:
    stderr = (
        "fatal: ambiguous argument 'HEAD': unknown revision or path not in the working tree.\n"
        "Use '--' to separate paths from revisions, like this:\n"
        "'git <command> [<revision>...] -- [<file>...]'\n"
    )
    assert clean_git_error(stderr).startswith("fatal: ambiguous argument")


def test_parse_helpers() -> None:
    assert parse_rev_list_count("42\n") == 42
    assert parse_rev_list_count("nonsense") == 0
    assert parse_name_email("Ada Lovelace <ada@example.com>") == ("Ada Lovelace", "ada@example.com")
    assert parse_shortstat(" 3 files changed, 12 insertions(+), 4 deletions(-)") == {
        "files_changed": 3,
        "additions": 12,
        "deletions": 4,
    }


def test_split_records_drops_empty_chunks() -> None:
    assert split_records(f"{RS}a{RS}{RS}b") == ["a", "b"]

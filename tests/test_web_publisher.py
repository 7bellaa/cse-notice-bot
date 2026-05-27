"""Tests for src/cse_bot/web_publisher.py."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cse_bot.models import TrackedDeadline
from cse_bot.web_publisher import git_publish, write_events_json


def _deadline(
    post_id: int = 1,
    title: str = "[장학] 테스트",
    url: str = "https://example.com/1",
    date_: str = "2026-06-22",
    category: str = "장학",
) -> TrackedDeadline:
    return TrackedDeadline(
        post_id=post_id, title=title, url=url, date=date_, category=category,
    )


class TestWriteEventsJson:
    def test_writes_fullcalendar_event_shape(self, tmp_path: Path) -> None:
        deadlines = [_deadline()]
        out = tmp_path / "events.json"

        write_events_json(deadlines, out)

        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1
        evt = data[0]
        assert evt["id"] == "1"
        assert evt["title"] == "[장학] 테스트"
        assert evt["start"] == "2026-06-22"
        assert evt["url"] == "https://example.com/1"
        assert evt["color"].startswith("#") and len(evt["color"]) == 7
        assert evt["extendedProps"]["category"] == "장학"

    def test_empty_input_writes_empty_array(self, tmp_path: Path) -> None:
        out = tmp_path / "events.json"
        write_events_json([], out)
        assert json.loads(out.read_text(encoding="utf-8")) == []

    def test_unknown_category_uses_default_color(self, tmp_path: Path) -> None:
        out = tmp_path / "events.json"
        write_events_json([_deadline(category="")], out)
        evt = json.loads(out.read_text(encoding="utf-8"))[0]
        # Default slate gray
        assert evt["color"] == "#6b7280"

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "path" / "events.json"
        write_events_json([_deadline()], out)
        assert out.exists()

    def test_korean_titles_not_escaped(self, tmp_path: Path) -> None:
        out = tmp_path / "events.json"
        write_events_json([_deadline(title="장학금 신청")], out)
        raw = out.read_text(encoding="utf-8")
        # Raw JSON should contain Korean characters directly, not \uXXXX escapes
        assert "장학금 신청" in raw

    def test_writes_atomically(self, tmp_path: Path) -> None:
        # Repeated writes should not leave .tmp behind
        out = tmp_path / "events.json"
        write_events_json([_deadline()], out)
        write_events_json([_deadline(post_id=2)], out)
        siblings = list(tmp_path.iterdir())
        assert all(p.suffix == ".json" for p in siblings)


class TestGitPublish:
    def test_skips_commit_when_no_diff(self, tmp_path: Path) -> None:
        with patch("cse_bot.web_publisher.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            )
            # First call (`git diff --quiet`) exits 0 → no changes
            published = git_publish([tmp_path], message="x", cwd=tmp_path)

        assert published is False
        # Only the diff check should be called
        calls = [c.args[0] for c in run.call_args_list]
        assert all("commit" not in args for args in calls)
        assert all("push" not in args for args in calls)

    def test_commits_and_pushes_when_diff_exists(self, tmp_path: Path) -> None:
        def fake_run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
            # git diff --quiet returns 1 if changes exist
            if "diff" in args and "--quiet" in args:
                return subprocess.CompletedProcess(args=args, returncode=1)
            if "rev-parse" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="abc123\n",
                )
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("cse_bot.web_publisher.subprocess.run", side_effect=fake_run) as run:
            published = git_publish([tmp_path], message="auto: test", cwd=tmp_path)

        assert published is True
        # add, commit, pull --rebase, push expected in sequence
        seen = [c.args[0] for c in run.call_args_list]
        assert any("add" in a for a in seen)
        assert any("commit" in a for a in seen)
        assert any("pull" in a and "--rebase" in a for a in seen)
        assert any("push" in a for a in seen)

    def test_pull_runs_before_push(self, tmp_path: Path) -> None:
        """Push must follow a successful rebase onto upstream."""
        def fake_run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
            if "diff" in args and "--quiet" in args:
                return subprocess.CompletedProcess(args=args, returncode=1)
            if "rev-parse" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="abc123\n",
                )
            return subprocess.CompletedProcess(args=args, returncode=0)

        with patch("cse_bot.web_publisher.subprocess.run", side_effect=fake_run) as run:
            git_publish([tmp_path], message="x", cwd=tmp_path)

        seen = [c.args[0] for c in run.call_args_list]
        pull_idx = next(i for i, a in enumerate(seen) if "pull" in a)
        push_idx = next(i for i, a in enumerate(seen) if "push" in a)
        assert pull_idx < push_idx

    def test_rolls_back_commit_when_push_fails(self, tmp_path: Path) -> None:
        """If push fails, the just-made commit must be reset so it does not
        accumulate on the local branch (which would diverge from origin
        forever after the first conflict)."""
        def fake_run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
            if "diff" in args and "--quiet" in args:
                return subprocess.CompletedProcess(args=args, returncode=1)
            if "rev-parse" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="pre-sha\n",
                )
            if "push" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stderr="fetch first",
                )
            return subprocess.CompletedProcess(args=args, returncode=0)

        with (
            patch("cse_bot.web_publisher.subprocess.run", side_effect=fake_run) as run,
            pytest.raises(RuntimeError, match="push"),
        ):
            git_publish([tmp_path], message="x", cwd=tmp_path)

        # The rollback step must invoke `git reset --mixed <pre-sha>`.
        reset_calls = [
            c.args[0] for c in run.call_args_list
            if "reset" in c.args[0] and "pre-sha" in c.args[0]
        ]
        assert reset_calls, "expected reset --mixed to be invoked on push failure"

    def test_rolls_back_commit_when_pull_rebase_fails(self, tmp_path: Path) -> None:
        def fake_run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
            if "diff" in args and "--quiet" in args:
                return subprocess.CompletedProcess(args=args, returncode=1)
            if "rev-parse" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="pre-sha\n",
                )
            if "pull" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stderr="rebase conflict",
                )
            return subprocess.CompletedProcess(args=args, returncode=0)

        with (
            patch("cse_bot.web_publisher.subprocess.run", side_effect=fake_run) as run,
            pytest.raises(RuntimeError, match="rebase"),
        ):
            git_publish([tmp_path], message="x", cwd=tmp_path)

        cmds = [c.args[0] for c in run.call_args_list]
        # Aborts any in-progress rebase, then resets.
        assert any("rebase" in a and "--abort" in a for a in cmds)
        assert any("reset" in a and "pre-sha" in a for a in cmds)
        # Push must NOT have been attempted after the failed rebase.
        assert not any("push" in a for a in cmds)

    def test_propagates_commit_failure_as_false(self, tmp_path: Path) -> None:
        def fake_run(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
            if "diff" in args:
                return subprocess.CompletedProcess(args=args, returncode=1)
            if "rev-parse" in args:
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="pre-sha\n",
                )
            if "commit" in args:
                return subprocess.CompletedProcess(args=args, returncode=1, stderr="x")
            return subprocess.CompletedProcess(args=args, returncode=0)

        with (
            patch("cse_bot.web_publisher.subprocess.run", side_effect=fake_run),
            pytest.raises(RuntimeError),
        ):
            git_publish([tmp_path], message="x", cwd=tmp_path)

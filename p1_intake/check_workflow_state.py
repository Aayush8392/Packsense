"""Workflow-state tripwire: is every workflow of this repository still `active`?

GitHub disables scheduled workflows in a public repository after 60 days of no repository activity, and the docs do not define
'activity' (see the keep-alive notes). This replaces guessing: once a week, read each workflow's `state` from the Actions API and fail
when any is not `active` (`disabled_inactivity`, `disabled_manually`, `disabled_fork`, `deleted`). The workflow's own file is in the
list, and a missed weekly ping at healthchecks.io is what would reveal a checker that was itself disabled.

Workflow names and paths are in this public repository anyway, so the log names them; no secret value is ever printed.
Configuration comes from environment variables:
  GITHUB_TOKEN, GITHUB_REPOSITORY (set by Actions), HEALTHCHECKS_PING_URL (optional), EXPECT_STATE (default `active`; a test input).
Exit codes: 0 every workflow is in the expected state, 1 at least one is not.
"""
import json
import os
import sys
import urllib.request

API = "https://api.github.com"


def not_in_state(workflows: list[dict], expect: str = "active") -> list[tuple[str, str, str]]:
    """(path, name, state) for every workflow whose state is not the expected one, sorted by path."""
    return sorted((w["path"], w.get("name", ""), w["state"]) for w in workflows if w["state"] != expect)


def fetch_workflows(repo: str, token: str) -> list[dict]:
    out, page = [], 1
    while True:
        req = urllib.request.Request(
            f"{API}/repos/{repo}/actions/workflows?per_page=100&page={page}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (a fixed https GitHub API URL)
            data = json.load(resp)
        out.extend(data["workflows"])
        if len(out) >= data["total_count"] or not data["workflows"]:
            return out
        page += 1


def ping(url: str, body: str, fail: bool) -> None:
    req = urllib.request.Request(url.rstrip("/") + ("/fail" if fail else ""), data=body.encode("utf-8"), method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (our own healthchecks ping URL)
        resp.read()


def main() -> int:
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    expect = os.environ.get("EXPECT_STATE") or "active"
    url = os.environ.get("HEALTHCHECKS_PING_URL", "")
    workflows = fetch_workflows(repo, token)
    bad = not_in_state(workflows, expect)
    if bad:
        lines = [f"{path}: {state}" for path, _, state in bad]
        print(f"FAIL: {len(bad)} of {len(workflows)} workflow(s) not {expect}:\n" + "\n".join(lines))
        if url:
            ping(url, f"{len(bad)} workflow(s) not {expect}:\n" + "\n".join(lines), fail=True)
        return 1
    print(f"ok: all {len(workflows)} workflows are {expect}")
    if url:
        ping(url, f"ok: all {len(workflows)} workflows are {expect}", fail=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

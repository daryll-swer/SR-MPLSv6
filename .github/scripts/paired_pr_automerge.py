"""Merge one pinned parent PR after its matching fork PR is integrated."""

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

PARENT = "daryll-swer/SR-MPLSv6"
FORK = "next-hopself/SR-MPLSv6"
MAIN = "main"
BUILD = "build.yml"
CONTROLLER = "paired-pr-automerge.yml"
DOC_PATHS = frozenset(f"draft-swer-spring-sr-mplsv6.{ext}" for ext in ("xml", "txt"))
SHA = re.compile(r"[0-9a-f]{40}")
PENDING = frozenset({"queued", "in_progress", "requested", "waiting", "pending"})
MAX_RESPONSE = 2 * 1024 * 1024
BUILD_STEPS = (
    "Render text, HTML, and expanded XML",
    "Check that the committed plain-text copy is up to date",
    "Run idnits",
)


class Blocked(Exception):
    """An API response or policy gate prevents further writes."""


class Waiting(Exception):
    """An expected incomplete state can be checked again later."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Blocked(message)


def sha(value: Any) -> str:
    require(isinstance(value, str) and SHA.fullmatch(value) is not None, "Invalid Git SHA")
    return value


def positive_id(value: Any) -> int:
    require(type(value) is int and 0 < value <= 2**53 - 1, "Invalid GitHub ID")
    return value


def timestamp(value: Any) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), "Invalid GitHub timestamp")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class Pins:
    parent_pr: int
    fork_pr: int
    head_ref: str
    head_sha: str
    parent_base_sha: str
    blobs: dict[str, str]

    @classmethod
    def parse(cls, raw: str) -> "Pins":
        require(len(raw) <= 2048, "Configuration exceeds 2048 characters")
        data = json.loads(raw, object_pairs_hook=unique_keys)
        keys = {"parent_pr", "fork_pr", "head_ref", "head_sha", "parent_base_sha", "blobs"}
        require(isinstance(data, dict) and data.keys() == keys, "Unexpected configuration keys")
        head_ref = data["head_ref"]
        require(
            isinstance(head_ref, str)
            and head_ref != MAIN
            and len(head_ref) <= 120
            and re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._/-]*", head_ref) is not None
            and ".." not in head_ref
            and not head_ref.startswith("-")
            and all(part and not part.startswith(".") and not part.endswith((".lock", "."))
                    for part in head_ref.split("/")),
            "Invalid topic branch",
        )
        blobs = data["blobs"]
        require(isinstance(blobs, dict) and blobs.keys() == DOC_PATHS, "Unexpected draft paths")
        head = sha(data["head_sha"])
        base = sha(data["parent_base_sha"])
        require(head != base, "The topic and parent base must differ")
        return cls(positive_id(data["parent_pr"]), positive_id(data["fork_pr"]), head_ref,
                   head, base, {path: sha(blob) for path, blob in blobs.items()})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class GitHub:
    def __init__(self, token: str, dry_run: bool) -> None:
        self.token = token
        self.dry_run = dry_run
        self.opener = build_opener(NoRedirect())

    def request(self, request: Request, expected: int) -> tuple[Any, bytes]:
        try:
            with self.opener.open(request, timeout=8) as response:
                require(response.status == expected, f"Unexpected HTTP {response.status}")
                data = response.read(MAX_RESPONSE + 1)
                require(len(data) <= MAX_RESPONSE, "GitHub response exceeded size limit")
                return response.headers, data
        except HTTPError as error:
            with error:
                raise Blocked(f"GitHub request returned HTTP {error.code}") from None
        except (URLError, TimeoutError, OSError):
            raise Blocked("GitHub request interrupted. Recheck GitHub state before retrying.") from None

    def api_request(self, repo: str, path: str, method: str = "GET",
                    body: dict[str, Any] | None = None) -> Request:
        require(repo in (PARENT, FORK), "Unexpected repository")
        require(method == "GET" or (repo == PARENT and not self.dry_run and bool(self.token)),
                "Repository write forbidden")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "paired-pr-automerge",
        }
        if repo == PARENT and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        return Request(f"https://api.github.com/repos/{repo}/{path}",
                       data=json.dumps(body).encode() if body is not None else None,
                       headers=headers, method=method)

    def json(self, repo: str, path: str, *, method: str = "GET",
             body: dict[str, Any] | None = None, expected: int = 200) -> Any:
        headers, data = self.request(self.api_request(repo, path, method, body), expected)
        # The controller expects small, narrowly filtered collections. A second
        # page could hide a newer CI run or additional changed files.
        require('rel="next"' not in headers.get("Link", ""), "GitHub listing exceeded one page")
        return None if expected == 204 else json.loads(data)


def collection(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = data[key]
    require(isinstance(items, list) and type(data["total_count"]) is int
            and len(items) == data["total_count"], "Incomplete GitHub listing")
    return items


def pull(api: GitHub, pins: Pins, repo: str) -> dict[str, Any]:
    number = pins.parent_pr if repo == PARENT else pins.fork_pr
    result = api.json(repo, f"pulls/{number}")
    require(type(result["number"]) is int and result["number"] == number
            and result["base"]["repo"]["full_name"] == repo
            and result["base"]["ref"] == MAIN, "Unexpected PR base or identity")
    require(result["head"]["repo"]["full_name"] == PARENT
            and result["head"]["ref"] == pins.head_ref
            and result["head"]["sha"] == pins.head_sha, "PR head differs from pinned topic")
    require(type(result["merged"]) is bool and result["state"] in ("open", "closed")
            and (not result["merged"] or result["state"] == "closed"), "Unknown PR state")
    return result


def ref_sha(api: GitHub, ref: str) -> str:
    result = api.json(PARENT, f"git/ref/heads/{quote(ref, safe='/')}")
    require(result["ref"] == f"refs/heads/{ref}" and result["object"]["type"] == "commit",
            "Unexpected parent ref response")
    return sha(result["object"]["sha"])


def commit(api: GitHub, repo: str, commit_sha: str) -> dict[str, Any]:
    result = api.json(repo, f"git/commits/{sha(commit_sha)}")
    require(result["sha"] == commit_sha, "Git commit SHA mismatch")
    return result


def root_tree(api: GitHub, repo: str, git_commit: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    tree_sha = sha(git_commit["tree"]["sha"])
    result = api.json(repo, f"git/trees/{tree_sha}")
    require(result["sha"] == tree_sha and result["truncated"] is False, "Incomplete Git tree")
    entries = result["tree"]
    require(isinstance(entries, list), "Invalid Git tree")
    tree = {item["path"]: (item["mode"], item["type"], sha(item["sha"])) for item in entries}
    require(len(tree) == len(entries), "Duplicate Git tree path")
    return tree


def expect_blobs(tree: dict[str, tuple[str, str, str]], pins: Pins) -> None:
    require(all(tree.get(path) == ("100644", "blob", blob) for path, blob in pins.blobs.items()),
            "Draft blob or mode mismatch")


def expect_pr_files(api: GitHub, pins: Pins, repo: str, pr: dict[str, Any]) -> None:
    require(type(pr["changed_files"]) is int and pr["changed_files"] == len(DOC_PATHS),
            "PR must change exactly two draft files")
    files = api.json(repo, f"pulls/{pr['number']}/files?per_page=10")
    require(isinstance(files, list) and len(files) == len(DOC_PATHS)
            and {item["filename"] for item in files} == DOC_PATHS
            and all(item["status"] == "modified" and item["sha"] == pins.blobs[item["filename"]]
                    for item in files), "PR file changes differ from the pinned draft")


def verify_parent_result(api: GitHub, pins: Pins, merge_sha: str) -> None:
    merge = commit(api, PARENT, merge_sha)
    require([parent["sha"] for parent in merge["parents"]]
            == [pins.parent_base_sha, pins.head_sha], "Merge commit has different parents")
    base = root_tree(api, PARENT, commit(api, PARENT, pins.parent_base_sha))
    result = root_tree(api, PARENT, merge)
    expect_blobs(result, pins)
    # A root tree entry commits to the entire subtree. This comparison also
    # rules out changes to workflows, the Makefile, and other build inputs.
    expected = base | {path: ("100644", "blob", blob) for path, blob in pins.blobs.items()}
    require(DOC_PATHS <= base.keys() and all(base[path] != expected[path] for path in DOC_PATHS)
            and result == expected, "Merge tree changes more or less than the pinned draft")


def verify_open_parent(api: GitHub, pins: Pins, pr: dict[str, Any]) -> str:
    require(pr["state"] == "open" and not pr["merged"] and pr["draft"] is False,
            "Parent PR must be open and ready for review")
    require(pr["base"]["sha"] == pins.parent_base_sha, "Parent PR base moved. Review and re-arm.")
    if pr["mergeable"] is None:
        raise Waiting("GitHub is calculating parent PR mergeability")
    require(pr["mergeable"] is True, "Parent PR is not mergeable")
    return sha(pr["merge_commit_sha"])


def latest_run(api: GitHub, *, event: str, head: str, branch: str,
               since: datetime, number: int | None = None) -> dict[str, Any] | None:
    query = urlencode({"event": event, "head_sha": head, "branch": branch, "per_page": 30})
    data = api.json(PARENT, f"actions/workflows/{BUILD}/runs?{query}")
    matching = []
    for run in collection(data, "workflow_runs"):
        require(run["path"] == f".github/workflows/{BUILD}" and run["event"] == event
                and run["head_sha"] == head and run["head_branch"] == branch
                and run["repository"]["full_name"] == PARENT
                and run["head_repository"]["full_name"] == PARENT, "Unexpected build workflow run")
        created = timestamp(run["created_at"])
        associations = run["pull_requests"]
        require(isinstance(associations, list), "Invalid workflow PR associations")
        if created >= since and (number is None or not associations
                                 or any(item["number"] == number for item in associations)):
            matching.append((created, positive_id(run["id"]), run))
    require(len({item[1] for item in matching}) == len(matching), "Duplicate workflow run")
    return max(matching, default=(None, None, None), key=lambda item: item[:2])[2]


def run_key(run: dict[str, Any]) -> tuple[int, int]:
    return positive_id(run["id"]), positive_id(run["run_attempt"])


def completed_jobs(api: GitHub, run: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    run_id, attempt = run_key(run)
    status = run["status"]
    if status in PENDING:
        raise Waiting(f"Build workflow run {run_id} is {status}")
    require(status == "completed" and run["conclusion"] == "success",
            f"Build workflow run {run_id} needs manual review")
    data = api.json(PARENT, f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=20")
    jobs = collection(data, "jobs")
    checked = {}
    for name in names:
        matches = [job for job in jobs if job["name"] == name]
        require(len(matches) == 1, f"Workflow run {run_id} is missing a unique {name} job")
        job = matches[0]
        require(job["run_id"] == run_id and job["head_sha"] == run["head_sha"]
                and job["status"] == "completed" and job["conclusion"] == "success",
                f"Workflow run {run_id} did not complete its {name} job successfully")
        checked[name] = job
    return checked


def verify_build_steps(build: dict[str, Any], tested_sha: str, tested_ref: str) -> None:
    steps = build["steps"]
    # The job's head_sha is the source commit for a PR run. The build step
    # records and verifies the synthetic merge revision that was checked out.
    for name in (f"Verify checked-out revision {tested_sha} at {tested_ref}", *BUILD_STEPS):
        matches = [step for step in steps if step["name"] == name]
        require(len(matches) == 1 and matches[0]["status"] == "completed"
                and matches[0]["conclusion"] == "success", f"Missing successful build step: {name}")


def resume_deployment(api: GitHub, pins: Pins, parent: dict[str, Any]) -> str:
    merge_sha = sha(parent["merge_commit_sha"])
    merged_at = timestamp(parent["merged_at"])
    verify_parent_result(api, pins, merge_sha)
    runs = {"event": "workflow_dispatch", "head": merge_sha, "branch": MAIN, "since": merged_at}
    run = latest_run(api, **runs)
    require(ref_sha(api, MAIN) == merge_sha, "Parent main moved after merge. Review deployment manually.")
    if run is None:
        if api.dry_run:
            return f"Would dispatch {BUILD} on main at {merge_sha}"
        result = api.json(PARENT, f"actions/workflows/{BUILD}/dispatches", method="POST",
                          body={"ref": MAIN, "inputs": {"expected_sha": merge_sha}})
        run_id = positive_id(result["workflow_run_id"])
        return f"Dispatched {BUILD} for {merge_sha}. Check run {run_id} on the next poll."
    jobs = completed_jobs(api, run, ("build", "deploy"))
    verify_build_steps(jobs["build"], merge_sha, f"refs/heads/{MAIN}")
    run_id, _ = run_key(run)
    if api.dry_run:
        return f"Build and deploy run {run_id} succeeded. Would disable {CONTROLLER}."
    api.json(PARENT, f"actions/workflows/{CONTROLLER}/disable", method="PUT", expected=204)
    return f"Build and deploy run {run_id} succeeded at {merge_sha}. Disabled {CONTROLLER}."


def reconcile(api: GitHub, pins: Pins) -> str:
    """Check immutable pins and perform at most one parent state change."""
    fork = pull(api, pins, FORK)
    parent = pull(api, pins, PARENT)
    require(fork["merged"] or fork["state"] == "open", "Fork PR was closed without merging")
    if not fork["merged"] and not api.dry_run:
        require(not parent["merged"], "Parent PR merged before the fork PR")
        raise Waiting("Fork PR is still open")
    if fork["merged"]:
        expect_pr_files(api, pins, FORK, fork)
        fork_merge = commit(api, FORK, sha(fork["merge_commit_sha"]))
        expect_blobs(root_tree(api, FORK, fork_merge), pins)
        if parent["merged"]:
            require(timestamp(fork["merged_at"]) <= timestamp(parent["merged_at"]),
                    "Parent PR merged before the fork PR")
            return resume_deployment(api, pins, parent)
    else:
        require(not parent["merged"], "Parent PR merged before the fork PR")
    merge_sha = verify_open_parent(api, pins, parent)
    require(ref_sha(api, MAIN) == pins.parent_base_sha, "Parent main moved. Review and re-arm.")
    require(ref_sha(api, pins.head_ref) == pins.head_sha, "Parent topic branch moved. Review and re-arm.")
    expect_pr_files(api, pins, PARENT, parent)
    expect_blobs(root_tree(api, PARENT, commit(api, PARENT, pins.head_sha)), pins)
    verify_parent_result(api, pins, merge_sha)
    query = {"event": "pull_request", "head": pins.head_sha, "branch": pins.head_ref,
             "since": timestamp(parent["created_at"]), "number": pins.parent_pr}
    run = latest_run(api, **query)
    if run is None:
        raise Waiting("No matching build workflow run for the parent PR yet")
    verify_build_steps(completed_jobs(api, run, ("build",))["build"], merge_sha,
                       f"refs/pull/{pins.parent_pr}/merge")
    if not fork["merged"]:
        return "Parent PR pins and CI verified. Waiting for the fork PR to merge."

    current_run = latest_run(api, **query)
    require(current_run is not None and run_key(current_run) == run_key(run)
            and current_run["status"] == "completed" and current_run["conclusion"] == "success",
            "Parent CI changed before merge. Recheck the latest attempt.")
    fork_now = pull(api, pins, FORK)
    require(fork_now["merged"] and fork_now["merge_commit_sha"] == fork["merge_commit_sha"],
            "Fork PR changed before merge")
    parent_now = pull(api, pins, PARENT)
    require(verify_open_parent(api, pins, parent_now) == merge_sha, "Parent test merge changed")
    require(ref_sha(api, pins.head_ref) == pins.head_sha, "Parent topic branch moved before merge")
    require(ref_sha(api, MAIN) == pins.parent_base_sha, "Parent main moved before merge")
    if api.dry_run:
        return f"Would merge parent PR #{pins.parent_pr} at {pins.head_sha}"
    # GitHub atomically checks the head SHA here. The endpoint has no base SHA guard.
    result = api.json(PARENT, f"pulls/{pins.parent_pr}/merge", method="PUT",
                      body={"sha": pins.head_sha, "merge_method": "merge"})
    require(result["merged"] is True, "GitHub rejected the parent merge")
    return f"Merged parent PR #{pins.parent_pr} at {sha(result['sha'])}. Deployment is the next poll."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="inspect GitHub state with GET only")
    args = parser.parse_args()
    try:
        if not args.dry_run or os.environ.get("GITHUB_ACTIONS") == "true":
            require(os.environ.get("GITHUB_ACTIONS") == "true"
                    and os.environ.get("GITHUB_REPOSITORY") == PARENT
                    and os.environ.get("GITHUB_REF") == "refs/heads/main"
                    and os.environ.get("GITHUB_EVENT_NAME") in ("schedule", "workflow_dispatch"),
                    "Controller requires a schedule or dispatch on the parent main branch")
        raw = os.environ.get("PAIRED_PR_AUTOMERGE", "")
        if not raw.strip():
            print("Controller is unarmed")
            return 0
        token = os.environ.get("GITHUB_TOKEN", "")
        require(bool(token) or args.dry_run, "GITHUB_TOKEN is required for controller writes")
        print(reconcile(GitHub(token, args.dry_run), Pins.parse(raw)))
    except Waiting as wait:
        print(f"Waiting: {wait}")
    except Blocked as error:
        print(f"Blocked: {error}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, AttributeError, ValueError, OSError):
        print("Blocked: Invalid configuration or unexpected GitHub response", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

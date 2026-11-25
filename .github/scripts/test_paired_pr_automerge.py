from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request

import paired_pr_automerge as controller

HEAD = "1" * 40
BASE = "2" * 40
FORK_MERGE = "3" * 40
TEST_MERGE = "4" * 40
PARENT_MERGE = "5" * 40
BASE_TREE = "6" * 40
RESULT_TREE = "7" * 40
HEAD_TREE = "8" * 40
FORK_TREE = "9" * 40
OLD_BLOB = "a" * 40
WRONG = "b" * 40
DOCS = sorted(controller.DOC_PATHS)
CREATED = "2026-11-25T01:00:00Z"
FORK_MERGED = "2026-11-25T02:00:00Z"
PARENT_MERGED = "2026-11-25T03:00:00Z"
PINS = {
    "parent_pr": 19,
    "fork_pr": 11,
    "head_ref": "draft/ipv6-te-router-id",
    "head_sha": HEAD,
    "parent_base_sha": BASE,
    "blobs": {DOCS[0]: "c" * 40, DOCS[1]: "d" * 40},
}
PARENT, FORK, BUILD = controller.PARENT, controller.FORK, controller.BUILD


def pr(number, repo):
    return {
        "number": number, "state": "open", "merged": False, "draft": False,
        "mergeable": True, "merge_commit_sha": TEST_MERGE, "changed_files": 2,
        "created_at": CREATED,
        "base": {"repo": {"full_name": repo}, "ref": "main", "sha": BASE},
        "head": {"repo": {"full_name": PARENT}, "ref": PINS["head_ref"], "sha": HEAD},
    }


def tree(tree_sha, blobs):
    return {
        "sha": tree_sha, "truncated": False,
        "tree": [{"path": ".github", "type": "tree", "mode": "040000", "sha": OLD_BLOB}]
        + [{"path": path, "type": "blob", "mode": "100644", "sha": blob}
           for path, blob in blobs.items()],
    }


def commit(commit_sha, tree_sha, parents=()):
    return {"sha": commit_sha, "tree": {"sha": tree_sha},
            "parents": [{"sha": parent} for parent in parents]}


def reference(ref, ref_sha):
    return {"ref": f"refs/heads/{ref}", "object": {"type": "commit", "sha": ref_sha}}


def run(id_number=22, *, head=HEAD, event="pull_request", branch=PINS["head_ref"], created=CREATED):
    return {
        "id": id_number, "run_attempt": 1, "status": "completed", "conclusion": "success",
        "path": f".github/workflows/{BUILD}", "event": event, "head_sha": head,
        "head_branch": branch, "repository": {"full_name": PARENT},
        "head_repository": {"full_name": PARENT}, "created_at": created, "pull_requests": [],
    }


def verification_step(sha=TEST_MERGE, ref="refs/pull/19/merge"):
    return f"Verify checked-out revision {sha} at {ref}"


def jobs(id_number=22, *, head=HEAD, names=("build",), verified=verification_step()):
    return {"total_count": len(names), "jobs": [
        {"id": 123 + index, "name": name, "run_id": id_number, "head_sha": head,
         "status": "completed", "conclusion": "success",
         "steps": [{"name": step, "status": "completed", "conclusion": "success"}
                   for step in (verified, *controller.BUILD_STEPS)]}
        for index, name in enumerate(names)
    ]}


def runs_path(event="pull_request", sha=HEAD, branch=PINS["head_ref"]):
    query = urlencode({"event": event, "head_sha": sha, "branch": branch, "per_page": 30})
    return f"actions/workflows/{BUILD}/runs?{query}"


class Fixture:
    def __init__(self, dry_run=False):
        self.pins = controller.Pins.parse(json.dumps(PINS))
        self.parent = pr(19, PARENT)
        self.fork = pr(11, FORK)
        self.fork.update(state="closed", merged=True, merge_commit_sha=FORK_MERGE, merged_at=FORK_MERGED)
        self.run = run()
        self.runs = {"total_count": 1, "workflow_runs": [self.run]}
        self.jobs = jobs()
        self.writes = []
        self.responses = {
            (FORK, "pulls/11"): self.fork,
            (PARENT, "pulls/19"): self.parent,
            (PARENT, "git/ref/heads/main"): reference("main", BASE),
            (PARENT, f"git/ref/heads/{PINS['head_ref']}"): reference(PINS["head_ref"], HEAD),
            (FORK, f"git/commits/{FORK_MERGE}"): commit(FORK_MERGE, FORK_TREE, (BASE, HEAD)),
            (FORK, f"git/trees/{FORK_TREE}"): tree(FORK_TREE, PINS["blobs"]),
            (PARENT, f"git/commits/{HEAD}"): commit(HEAD, HEAD_TREE),
            (PARENT, f"git/trees/{HEAD_TREE}"): tree(HEAD_TREE, PINS["blobs"]),
            (PARENT, f"git/commits/{BASE}"): commit(BASE, BASE_TREE),
            (PARENT, f"git/trees/{BASE_TREE}"): tree(BASE_TREE, dict.fromkeys(DOCS, OLD_BLOB)),
            (PARENT, f"git/commits/{TEST_MERGE}"): commit(TEST_MERGE, RESULT_TREE, (BASE, HEAD)),
            (PARENT, f"git/trees/{RESULT_TREE}"): tree(RESULT_TREE, PINS["blobs"]),
            (PARENT, runs_path()): self.runs,
            (PARENT, "actions/runs/22/attempts/1/jobs?per_page=20"): self.jobs,
            (PARENT, "pulls/19/merge"): {"merged": True, "sha": PARENT_MERGE},
        }
        for repo, number in ((PARENT, 19), (FORK, 11)):
            self.responses[repo, f"pulls/{number}/files?per_page=10"] = [
                {"filename": path, "status": "modified", "sha": blob}
                for path, blob in self.pins.blobs.items()
            ]
        self.api = Mock(spec=controller.GitHub)
        self.api.dry_run = dry_run
        self.api.json.side_effect = self.reply

    def reply(self, repo, path, *, method="GET", body=None, expected=200):
        if method != "GET":
            self.writes.append((repo, path, method, body, expected))
        response = self.responses[repo, path]
        if isinstance(response, Exception):
            raise response
        return deepcopy(response() if callable(response) else response)

    def resume(self, deployment=None, jobs_result=None):
        self.parent.update(state="closed", merged=True, merge_commit_sha=PARENT_MERGE, merged_at=PARENT_MERGED)
        self.responses[PARENT, "git/ref/heads/main"] = reference("main", PARENT_MERGE)
        self.responses[PARENT, f"git/commits/{PARENT_MERGE}"] = commit(PARENT_MERGE, RESULT_TREE, (BASE, HEAD))
        self.responses[PARENT, runs_path("workflow_dispatch", PARENT_MERGE, "main")] = {
            "total_count": int(deployment is not None), "workflow_runs": [deployment] if deployment else [],
        }
        self.responses[PARENT, f"actions/workflows/{BUILD}/dispatches"] = {"workflow_run_id": 70}
        self.responses[PARENT, "actions/workflows/paired-pr-automerge.yml/disable"] = None
        self.responses[PARENT, "actions/runs/70/attempts/1/jobs?per_page=20"] = (
            jobs_result if jobs_result is not None else jobs(
                70, head=PARENT_MERGE, names=("build", "deploy"),
                verified=verification_step(PARENT_MERGE, "refs/heads/main"),
            )
        )

    def reconcile(self):
        return controller.reconcile(self.api, self.pins)


class PinsTests(TestCase):
    def test_valid_pins(self):
        pins = controller.Pins.parse(json.dumps(PINS))
        self.assertEqual(pins.head_ref, PINS["head_ref"])
        self.assertEqual(pins.head_sha, HEAD)

    def test_invalid_pins(self):
        for key, value in (
            ("parent_pr", True), ("parent_pr", "19"), ("fork_pr", 0),
            ("head_sha", HEAD[:-1]), ("head_sha", "A" * 40), ("head_sha", BASE),
            ("head_ref", "main"), ("head_ref", "-topic"), ("head_ref", "a//b"),
            ("head_ref", "a/../b"), ("head_ref", "a.lock/b"), ("head_ref", "topic?foo=1"),
            ("blobs", {**PINS["blobs"], "Makefile": OLD_BLOB}), ("repo", PARENT),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(controller.Blocked):
                controller.Pins.parse(json.dumps({**PINS, key: value}))
        repeated = json.dumps(PINS)[:-1] + ', "fork_pr": 11}'
        with self.assertRaises(controller.Blocked):
            controller.Pins.parse(repeated)


class ReconcileTests(TestCase):
    def assert_blocked_without_writes(self, fixture, pattern):
        with self.assertRaisesRegex(controller.Blocked, pattern):
            fixture.reconcile()
        self.assertEqual(fixture.writes, [])

    def test_fork_open_waits_even_if_other_evidence_passes(self):
        fixture = Fixture()
        fixture.fork.update(state="open", merged=False, approved=True)
        with self.assertRaisesRegex(controller.Waiting, "Fork PR is still open"):
            fixture.reconcile()
        self.assertEqual(fixture.writes, [])
        fixture.api.dry_run = True
        self.assertIn("Parent PR pins and CI verified", fixture.reconcile())
        self.assertEqual(fixture.writes, [])

    def test_each_changed_pr_gate_prevents_merge(self):
        for repo, keys, value, message in (
            (FORK, ("merged",), False, "closed without merging"),
            (FORK, ("number",), 12, "Unexpected PR base"),
            (FORK, ("base", "ref"), "dev", "Unexpected PR base"),
            (FORK, ("base", "repo", "full_name"), PARENT, "Unexpected PR base"),
            (FORK, ("head", "sha"), WRONG, "PR head differs"),
            (FORK, ("head", "ref"), "draft/other", "PR head differs"),
            (FORK, ("head", "repo", "full_name"), FORK, "PR head differs"),
            (FORK, ("changed_files",), 3, "exactly two"),
            (PARENT, ("draft",), True, "ready for review"),
            (PARENT, ("state",), "closed", "ready for review"),
            (PARENT, ("base", "ref"), "dev", "Unexpected PR base"),
            (PARENT, ("base", "sha"), WRONG, "base moved"),
            (PARENT, ("head", "sha"), WRONG, "PR head differs"),
            (PARENT, ("head", "ref"), "draft/other", "PR head differs"),
            (PARENT, ("changed_files",), 1, "exactly two"),
            (PARENT, ("mergeable",), False, "not mergeable"),
        ):
            with self.subTest(repo=repo, keys=keys, value=value):
                fixture = Fixture()
                field = fixture.parent if repo == PARENT else fixture.fork
                for key in keys[:-1]:
                    field = field[key]
                field[keys[-1]] = value
                self.assert_blocked_without_writes(fixture, message)

    def test_files_trees_and_live_refs_prevent_merge(self):
        cases = (
            (FORK, f"git/trees/{FORK_TREE}", tree(FORK_TREE, dict.fromkeys(DOCS, WRONG)), "blob or mode"),
            (FORK, f"git/trees/{FORK_TREE}", {**tree(FORK_TREE, PINS["blobs"]), "truncated": True}, "Incomplete Git tree"),
            (PARENT, f"git/trees/{HEAD_TREE}", tree(HEAD_TREE, dict.fromkeys(DOCS, WRONG)), "blob or mode"),
            (PARENT, f"git/trees/{RESULT_TREE}", tree(RESULT_TREE, dict.fromkeys(DOCS, WRONG)), "blob or mode"),
            (PARENT, f"git/commits/{TEST_MERGE}", commit(TEST_MERGE, RESULT_TREE, (WRONG, HEAD)), "different parents"),
            (PARENT, "git/ref/heads/main", reference("main", WRONG), "main moved"),
            (PARENT, f"git/ref/heads/{PINS['head_ref']}", reference(PINS["head_ref"], WRONG), "branch moved"),
        )
        for repo, path, data, message in cases:
            with self.subTest(path=path, repo=repo):
                fixture = Fixture()
                fixture.responses[repo, path] = data
                self.assert_blocked_without_writes(fixture, message)
        fixture = Fixture()
        fixture.responses[FORK, f"git/trees/{FORK_TREE}"]["tree"][1]["mode"] = "120000"
        self.assert_blocked_without_writes(fixture, "blob or mode")
        fixture = Fixture()
        fixture.responses[PARENT, f"git/trees/{RESULT_TREE}"]["tree"][0]["sha"] = WRONG
        self.assert_blocked_without_writes(fixture, "Merge tree changes")
        fixture = Fixture()
        fixture.responses[PARENT, "pulls/19/files?per_page=10"][0]["filename"] = "Makefile"
        self.assert_blocked_without_writes(fixture, "file changes differ")

    def test_fork_squash_or_rebase_may_pass(self):
        fixture = Fixture(dry_run=True)
        fixture.responses[FORK, f"git/commits/{FORK_MERGE}"]["parents"] = [{"sha": BASE}]
        self.assertIn("Would merge parent PR", fixture.reconcile())
        self.assertEqual(fixture.writes, [])

    def test_missing_pr_merge_sha_blocks_writes(self):
        for target in ("parent", "fork"):
            with self.subTest(pr=target):
                fixture = Fixture()
                del getattr(fixture, target)["merge_commit_sha"]
                self.assert_blocked_without_writes(fixture, "did not return the PR merge commit SHA")

    def test_incomplete_ci_waits(self):
        for status in controller.PENDING:
            with self.subTest(status=status):
                fixture = Fixture()
                fixture.run.update(status=status, conclusion=None)
                with self.assertRaises(controller.Waiting):
                    fixture.reconcile()
                self.assertEqual(fixture.writes, [])
        fixture = Fixture()
        fixture.run["created_at"] = "2026-11-25T00:01:00Z"
        with self.assertRaisesRegex(controller.Waiting, "No matching"):
            fixture.reconcile()
        self.assertEqual(fixture.writes, [])

    def test_ci_gate_requires_current_checkout_and_build(self):
        for mutate, message in (
            (lambda f: f.run.update(head_sha=WRONG), "Unexpected build workflow run"),
            (lambda f: f.run.update(path=".github/workflows/impostor.yml"), "Unexpected build workflow run"),
            (lambda f: f.run.update(conclusion="failure"), "manual review"),
            (lambda f: f.jobs["jobs"][0].update(conclusion="skipped"), "did not complete"),
            (lambda f: f.jobs["jobs"][0]["steps"][0].update(conclusion="skipped"), "Missing successful build step"),
            (lambda f: f.jobs["jobs"][0]["steps"][0].update(name=verification_step(WRONG)), "Missing successful build step"),
            (lambda f: f.jobs["jobs"][0]["steps"][0].update(name=verification_step(ref="refs/pull/20/merge")),
             "Missing successful build step"),
            (lambda f: f.runs.update(total_count=2), "Incomplete GitHub listing"),
        ):
            with self.subTest(message=message):
                fixture = Fixture()
                mutate(fixture)
                self.assert_blocked_without_writes(fixture, message)

    def test_latest_run_wins_and_final_lookups_block_drift(self):
        fixture = Fixture()
        newer = run(23)
        newer.update(status="queued", conclusion=None)
        fixture.runs.update(total_count=2, workflow_runs=[fixture.run, newer])
        with self.assertRaisesRegex(controller.Waiting, "23 is queued"):
            fixture.reconcile()
        self.assertEqual(fixture.writes, [])
        for repo, path, change, message in (
            (PARENT, runs_path(), {"workflow_runs": [newer]}, "CI changed"),
            (FORK, "pulls/11", {"merge_commit_sha": WRONG}, "Fork PR changed"),
            (PARENT, "pulls/19", {"merge_commit_sha": WRONG}, "test merge changed"),
            (PARENT, "git/ref/heads/main", {"object": {"sha": WRONG, "type": "commit"}}, "main moved before merge"),
        ):
            with self.subTest(path=path):
                fixture = Fixture()
                initial = fixture.responses[repo, path]
                answers = iter([initial, {**initial, **change}])
                fixture.responses[repo, path] = lambda: next(answers)
                self.assert_blocked_without_writes(fixture, message)

    def test_only_approved_merge_is_sent_then_later_resume(self):
        fixture = Fixture()
        self.assertIn(f"Merged parent PR #19 at {PARENT_MERGE}", fixture.reconcile())
        self.assertEqual(fixture.writes, [
            (PARENT, "pulls/19/merge", "PUT", {"sha": HEAD, "merge_method": "merge"}, 200)
        ])
        fixture = Fixture(dry_run=True)
        self.assertIn("Would merge parent PR", fixture.reconcile())
        self.assertEqual(fixture.writes, [])

    def test_merge_409_or_false_stops_before_deploy(self):
        for failure in (controller.Blocked("GitHub request returned HTTP 409"), {"merged": False}):
            fixture = Fixture()
            fixture.responses[PARENT, "pulls/19/merge"] = failure
            with self.assertRaises(controller.Blocked):
                fixture.reconcile()
            self.assertEqual([item[1] for item in fixture.writes], ["pulls/19/merge"])

    def test_deploy_resume_then_success_disables_only_controller(self):
        fixture = Fixture()
        fixture.resume()
        self.assertIn("Check run 70", fixture.reconcile())
        dispatch = f"actions/workflows/{BUILD}/dispatches"
        body = {"ref": "main", "inputs": {"expected_sha": PARENT_MERGE}}
        self.assertEqual(fixture.writes, [(PARENT, dispatch, "POST", body, 200)])
        fixture.resume(run(70, head=PARENT_MERGE, event="workflow_dispatch", branch="main", created=PARENT_MERGED))
        self.assertIn("Build and deploy run 70 succeeded", fixture.reconcile())
        self.assertEqual(fixture.writes[1:], [
            (PARENT, "actions/workflows/paired-pr-automerge.yml/disable", "PUT", None, 204)
        ])

    def test_dry_run_deploy_paths_have_no_writes(self):
        fixture = Fixture(dry_run=True)
        fixture.resume()
        self.assertIn("Would dispatch", fixture.reconcile())
        fixture.resume(run(70, head=PARENT_MERGE, event="workflow_dispatch", branch="main", created=PARENT_MERGED))
        self.assertIn("Would disable", fixture.reconcile())
        self.assertEqual(fixture.writes, [])

    def test_deploy_requires_expected_merge_and_still_current_main(self):
        fixture = Fixture()
        fixture.resume()
        fixture.responses[PARENT, "git/ref/heads/main"] = reference("main", WRONG)
        self.assert_blocked_without_writes(fixture, "main moved after merge")
        fixture = Fixture()
        fixture.resume()
        fixture.parent["merged_at"] = CREATED
        self.assert_blocked_without_writes(fixture, "before the fork")
        fixture = Fixture()
        fixture.resume()
        fixture.responses[PARENT, f"git/commits/{PARENT_MERGE}"]["parents"] = [{"sha": WRONG}, {"sha": HEAD}]
        self.assert_blocked_without_writes(fixture, "different parents")

    def test_uncertain_dispatch_is_reconciled_without_another_write(self):
        fixture = Fixture()
        fixture.resume()
        fixture.responses[PARENT, f"actions/workflows/{BUILD}/dispatches"] = controller.Blocked("interrupted")
        with self.assertRaisesRegex(controller.Blocked, "interrupted"):
            fixture.reconcile()
        dispatched = run(70, head=PARENT_MERGE, event="workflow_dispatch", branch="main", created=PARENT_MERGED)
        dispatched.update(status="in_progress", conclusion=None)
        fixture.resume(dispatched)
        with self.assertRaisesRegex(controller.Waiting, "70 is in_progress"):
            fixture.reconcile()
        self.assertEqual(len(fixture.writes), 1)

    def test_failed_dispatch_job_requires_manual_action(self):
        fixture = Fixture()
        dispatched = run(70, head=PARENT_MERGE, event="workflow_dispatch", branch="main", created=PARENT_MERGED)
        dispatched["conclusion"] = "failure"
        fixture.resume(dispatched)
        self.assert_blocked_without_writes(fixture, "manual review")
        dispatched["conclusion"] = "success"
        deployment_jobs = jobs(70, head=PARENT_MERGE, names=("build", "deploy"))
        deployment_jobs["jobs"][1]["conclusion"] = "skipped"
        fixture.resume(dispatched, jobs_result=deployment_jobs)
        self.assert_blocked_without_writes(fixture, "did not complete its deploy job")
        deployment_jobs["jobs"][1]["conclusion"] = "success"
        self.assert_blocked_without_writes(fixture, "Missing successful build step")


class TransportTests(TestCase):
    def test_dry_run_and_fork_writes_rejected_before_network(self):
        writer = controller.GitHub("secret", False)
        reader = controller.GitHub("secret", True)
        with self.assertRaisesRegex(controller.Blocked, "write forbidden"):
            writer.api_request(FORK, "pulls/11/merge", "PUT")
        with self.assertRaisesRegex(controller.Blocked, "write forbidden"):
            reader.api_request(PARENT, "pulls/19/merge", "PUT")
        self.assertIsNone(reader.api_request(FORK, "pulls/11").get_header("Authorization"))

    def test_dispatch_uses_run_id_api_while_pr_uses_merge_commit_api(self):
        writer = controller.GitHub("secret", False)
        pull_request = writer.api_request(FORK, "pulls/11")
        self.assertEqual(pull_request.get_header("X-github-api-version"), "2022-11-28")
        dispatch = writer.api_request(PARENT, f"actions/workflows/{BUILD}/dispatches", "POST")
        self.assertEqual(dispatch.get_header("X-github-api-version"), "2026-03-10")

    def test_non200_is_blocked_without_logging_body(self):
        reader = controller.GitHub("secret", True)
        url = "https://api.github.com/error"
        with patch.object(reader.opener, "open", side_effect=HTTPError(url, 403, "secret", {}, None)):
            with self.assertRaisesRegex(controller.Blocked, "^GitHub request returned HTTP 403$"):
                reader.request(Request(url), 200)

    def test_second_page_is_blocked(self):
        reader = controller.GitHub("secret", True)
        with patch.object(reader, "request", return_value=({"Link": '<url>; rel="next"'}, b"[]")):
            with self.assertRaisesRegex(controller.Blocked, "exceeded one page"):
                reader.json(PARENT, "pulls/19/files")

    def test_cli_rejects_wrong_runtime_and_allows_unarmed_main(self):
        context = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": PARENT,
                   "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "schedule"}
        with patch("sys.argv", ["paired_pr_automerge.py"]), patch.dict(os.environ, context, clear=True):
            with patch("builtins.print"):
                self.assertEqual(controller.main(), 0)
                os.environ["GITHUB_REF"] = "refs/heads/topic"
                self.assertEqual(controller.main(), 1)


class CheckoutGuardTests(TestCase):
    def test_checkout_and_dispatch_must_match_the_expected_revision(self):
        script = Path(__file__).with_name("verify-checked-out-revision.sh").resolve()
        root = script.parents[2]
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        different = "f" * 40 if actual != "f" * 40 else "e" * 40
        for workflow_sha, expected_sha, exit_code in (
            (actual, "", 0),
            (actual, actual, 0),
            (actual, different, 1),
            (different, different, 1),
        ):
            with self.subTest(workflow_sha=workflow_sha, expected_sha=expected_sha):
                env = {**os.environ, "GITHUB_SHA": workflow_sha, "EXPECTED_SHA": expected_sha}
                result = subprocess.run(["bash", str(script)], env=env, cwd=root, check=False)
                self.assertEqual(result.returncode, exit_code)

# Paired PR auto-merge

The parent controller polls at minutes 7, 22, 37 and 52 of each hour. It
merges the pinned parent PR after the pinned fork PR has merged the same
reviewed draft and the current parent merge revision has passed CI. An empty
`PAIRED_PR_AUTOMERGE` repository Actions variable leaves the controller idle.

## Arm one pair

After both PRs exist, save the exact pins as one JSON object. Replace all
example numbers and hashes with the reviewed values.

```json
{
  "parent_pr": 19,
  "fork_pr": 11,
  "head_ref": "draft/ipv6-te-router-id",
  "head_sha": "1111111111111111111111111111111111111111",
  "parent_base_sha": "2222222222222222222222222222222222222222",
  "blobs": {
    "draft-swer-spring-sr-mplsv6.xml": "3333333333333333333333333333333333333333",
    "draft-swer-spring-sr-mplsv6.txt": "4444444444444444444444444444444444444444"
  }
}
```

Both PRs must use the named topic branch in `daryll-swer/SR-MPLSv6` at the
same `head_sha`. Their base branches are `main` in `daryll-swer/SR-MPLSv6`
and `next-hopself/SR-MPLSv6`, respectively. Use the parent `main` commit for
`parent_base_sha`. The blob IDs are the Git object IDs shown by
`git ls-tree <head_sha> -- <draft.xml> <draft.txt>`. Both entries must be
ordinary non-executable files with mode `100644`.

Check the pins locally with GET-only mode before adding the variable. A
completed parent build can be verified while the fork PR remains open.

```sh
PAIRED_PR_AUTOMERGE="$(cat paired-pr-pins.json)" \
  python3 .github/scripts/paired_pr_automerge.py --dry-run
```

Set the variable in the parent repository to arm the schedule. On GitHub,
**Run workflow** on `main` offers a `dry-run` option for a GET-only check or a
normal run to advance the controller immediately.

```sh
gh variable set PAIRED_PR_AUTOMERGE -R daryll-swer/SR-MPLSv6 < paired-pr-pins.json
```

Review new pins and CI evidence before updating the variable after a head,
base or content change. Clear the variable or disable the controller workflow
to disarm future runs. To stop immediately, also cancel any queued or running
controller jobs and verify the parent PR state. An active run may already have
read the variable or sent a merge request. Before enabling a controller that
has completed a pair, replace the old variable with the newly reviewed pins
or clear it.

## Monitor and recover

After a successful parent merge, a later poll verifies the immutable merge
commit and dispatches `build.yml` on `main` with that expected SHA. The
checkout guard stops the build if the ref resolves to a different commit. A
later poll verifies successful `build` and `deploy` jobs for that exact run
attempt, then disables `paired-pr-automerge.yml`.

A failed deployment requires operator review. Rerun all jobs in the matching
failed run to provide a complete new attempt. If `main` has advanced, review
its publication separately. A request interrupted after dispatch can take
time to appear in the run list. Let a scheduled poll reconcile the run and
check the Actions UI before triggering another dispatch. GitHub supplies no
dispatch idempotency key, so visibility delays can produce duplicate equivalent
runs. [Workflow dispatch and run endpoints](https://docs.github.com/en/rest/actions/workflows?apiVersion=2026-03-10)

GitHub atomically checks the pinned head during merge. A concurrent parent
`main` update can occur between the final base read and the merge request.
Coordinate other parent changes during the merge window. The controller
verifies both parents and the exact resulting tree before deploying.
[Merge endpoint](https://docs.github.com/en/rest/pulls/pulls?apiVersion=2026-03-10#merge-a-pull-request)

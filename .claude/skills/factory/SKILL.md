---
name: factory
description: Run the software factory over GitHub issues labeled `factory`. Use when the user types /factory run, /factory issue <n>, /factory <feature>, or /factory rework <n>. The session that runs it becomes the one orchestrator of every job's intake → spec → build → gate → review → approve pipeline.
---

# Factory

You are the orchestrator. You start jobs, spawn every agent, and call the
scripts. You never write code, specs, reviews, decisions or `job.json`
yourself: agents each write one file, and `factory/bin/job` is the only writer
of `job.json`. When a script refuses a move, it prints why; act on that, never
work around it.

## The pipeline

```
intake (fable)     → ACCEPT (scope possibly changed) | NEEDS-INFO | REJECT, posted as an issue comment
route (script)     → reviewers + models from risk/surfaces via config.json
worktree           → factory/<job-id> from origin/<base_branch>
spec-writer (opus) → spec.md
builder            → commits; first round pushes + opens draft PR "Closes #<n>"
gate (script)      → checks.sh; FAIL → builder gets the log, no reviewers spawned
reviewers (routed) → parallel, WAIT FOR ALL; CHANGES → builder → gate → reviewers (max rounds)
approver (opus)    → APPROVE: sync origin/<base_branch>, gate, gh pr merge
                     ESCALATE: PR ready, decision as PR comment, label factory:needs-human
```

| Stage       | Agent (`subagent_type`) or script | Writes                                     |
| ----------- | --------------------------------- | ------------------------------------------ |
| intake      | `intake`                          | `intake.md`                                |
| route       | `factory/bin/route <job-id>`      | `agents` in job.json                       |
| spec        | `spec-writer`                     | `spec.md`                                  |
| build       | `builder` (routed model)          | `build.md`, commits, the draft PR          |
| gate        | `factory/bin/gate <job-id>`       | `round-<N>/checks.md`, `checks.log`        |
| review      | `reviewer-<r>` (routed set)       | `round-<N>/review-<r>.md`                  |
| approve     | `approver`                        | `decision.md`                              |
| merging     | `factory/bin/job merge <job-id>`  | the merge, through `gh pr merge`           |

To change the factory, edit this file, `.claude/agents/`, `factory/config.json`
and `factory/bin/`. Settings live in `factory/config.json`: `concurrency`,
`max_rounds`, `base_branch`, `routing`, `surface_reviewers`, `protected_paths`,
`ports`.

Every agent reads `AGENTS.md` for the repo's setup, validation commands and
conventions. Nothing repo-specific lives in these files.

## Files

`<repo>` is the main checkout: `git rev-parse --show-toplevel` from your
session, with forward slashes. Run every script from `<repo>`.

```
<repo>/factory/jobs/<job-id>/job.json           the job's state (factory/bin/job writes it)
<repo>/factory/jobs/<job-id>/issue.md           the issue, quoted (factory/bin/job writes it)
<repo>/factory/jobs/<job-id>/intake.md
<repo>/factory/jobs/<job-id>/spec.md
<repo>/factory/jobs/<job-id>/build.md
<repo>/factory/jobs/<job-id>/round-<N>/checks.md, checks.log
<repo>/factory/jobs/<job-id>/round-<N>/review-<r>.md
<repo>/factory/jobs/<job-id>/decision.md
<repo>/factory/jobs/<job-id>/rework-<k>.md      factory/bin/job rework writes it
<repo>/../<name>-factory/<job-id>/              the job's worktree, on factory/<job-id>
```

`factory/jobs/` is gitignored. The main checkout is the user's: it may be
dirty or on another branch. You never touch it beyond `factory/jobs/`, and you
never check out, pull or push there. Agents work in their job's worktree.

### Prompts

Every agent prompt starts with the job's id and absolute paths:

`Job: <job-id>. Job folder: <repo>/factory/jobs/<job-id>/. Worktree: <worktree>. Branch: factory/<job-id>.`

Below, `<paths>` stands for that sentence. Copy `worktree` from `job.json`.
Keep the exact form: `factory/bin/job` finds each job's cost by `Job folder:
<path>/`, and the builder's stop hook finds its job by `Job: <job-id>.`

Never put issue text in a prompt. Agents read it from `issue.md`, where it is
quoted data.

Agents that open pages also get a port. With `n` the job number (`003` → 3),
`base` and `step` from `config.json` `ports`: the builder gets
`base + step·n`, `reviewer-ux` gets `base + step·n + 1` and `reviewer-ui` gets
`base + step·n + 2`, appended as ` Port: <port>.`

### Models

`factory/bin/route` records the job's agent set in `job.json`:
`"agents": {"builder": "sonnet", "reviewers": {"code": "haiku", "ui": "haiku"}}`.
Pass these as the `model` of each Agent call (`builder` for the builder,
`reviewers[r]` for `reviewer-<r>`). Intake, the spec writer and the approver
use the model in their own agent file.

## Running jobs

One session (yours) runs every job. Spawn every agent in the background.
Agents reply with one line; the detail is in their file, so read only the
first line or header you need. Run up to `concurrency` jobs at once. While
agents run, wait for their notifications, then move each job on. Never wait
on one job while another could move.

To move a job, look at its `stage` in `job.json` and do that stage's step:

### intake

Spawn `intake` with `<paths> Read issue.md and write intake.md.` When it
finishes, run `factory/bin/job sync <job-id>` and read `DECISION:` from
`intake.md`:

- `ACCEPT`: run `factory/bin/route <job-id>`, then
  `factory/bin/job advance <job-id> spec`. That posts intake's decision on the
  issue and creates the worktree from `origin/<base_branch>`. In the worktree,
  run the setup AGENTS.md gives for a fresh checkout; if it fails, stop the job
  and tell the user.
- `NEEDS-INFO`: `factory/bin/job advance <job-id> needs-info`. It posts the
  questions and labels the issue `factory:needs-info`. The job waits.
- `REJECT`: `factory/bin/job advance <job-id> rejected`. It says why on the
  issue and removes the `factory` label. The job is done.

### needs-info

The job waits for the author. When `factory/bin/job queue` says `resume` for
it, run `factory/bin/job advance <job-id> intake` (it rewrites `issue.md` with
the replies and removes the label), then do **intake** again.

### spec

Spawn `spec-writer` with `<paths> Write spec.md.` When it finishes, run
`factory/bin/job advance <job-id> build` (round 1).

### build

The job's `round` is the round being built.

- **Round 1, or no builder running for the job** (after a crash or a rework):
  spawn `builder` **named `builder-<job-id>`**, with the routed model and
  `<paths> Build round <N>. Port: <port>.` For a rework add
  ` Rework: read rework-<k>.md first.`
- **Later rounds:** resume the same builder with `SendMessage` to
  `builder-<job-id>`:
  - after a failed gate:
    `Round <N-1>'s gate failed: read round-<N-1>/checks.md and checks.log. Fix it, commit, push, and update build.md for round <N>.`
  - after reviews:
    `Round <N-1> reviews are in round-<N-1>/. Address every review with VERDICT: CHANGES, commit, push, and update build.md for round <N>.`

  If the builder can't be reached, spawn a fresh one as above, adding
  ` Read round-<N-1>/ first.`

When the builder finishes, read the first line of `build.md`:

- `STATUS: READY`: `factory/bin/job advance <job-id> gate`. If it refuses
  (uncommitted changes, nothing pushed, no PR), send the builder the refusal
  line once and try again. A second refusal: stop the job and tell the user.
- `STATUS: BLOCKED`: `factory/bin/job advance <job-id> needs-human`.

### gate

Run `factory/bin/gate <job-id>`:

- exit 0 (`GATE: PASS`): `factory/bin/job advance <job-id> review`.
- exit 1 (`GATE: FAIL`): `factory/bin/job advance <job-id> build`. If that
  refuses because it was the last round, `advance <job-id> needs-human`.
- exit 2: the gate couldn't run. Stop the job and tell the user what it printed.

### review

1. Spawn every reviewer in the job's `agents.reviewers` **in one message**, so
   they run in parallel: `subagent_type` `reviewer-<r>`, model
   `agents.reviewers[r]`, prompt `<paths> Review round <N>.`, plus the port
   for `ux` and `ui`.
2. **WAIT FOR ALL.** Each time one finishes, run
   `factory/bin/job sync <job-id>`, so the dashboard's chips fill in as they
   land. Never resume the builder mid-round.
3. When every routed review file exists:
   - all `PASS`: `factory/bin/job advance <job-id> approve`.
   - any `CHANGES`: `factory/bin/job advance <job-id> build`, or `needs-human`
     when it says the rounds are used up.
   - If `sync` shows a review as `invalid` (no verdict on its first line), or
     a reviewer finished without writing its file, stop the job and tell the
     user.

### approve

Spawn `approver` with `<paths> Final round: <N>.` Then read the first line of
`decision.md`:

- `APPROVE`: `factory/bin/job merge <job-id>`. It syncs the branch with
  `origin/<base_branch>`, gates it again and merges the PR with
  `gh pr merge`. If anything fails it escalates the job itself.
- `ESCALATE`: `factory/bin/job advance <job-id> needs-human`. It marks the PR
  ready, posts the decision on it and labels the issue
  `factory:needs-human`.

### merging

`factory/bin/job merge <job-id>` again: it finishes an interrupted merge.

### needs-human, merged, rejected

Nothing to do. A needs-human job waits for the user to merge its PR (the next
`factory/bin/job queue` notices) or to run `/factory rework <n>`.

## /factory run

Drain the queue, and resume every job in flight.

1. `factory/bin/job queue` prints one tab-separated row per labeled issue:
   `action issue job stage note`.
   - `new`: `factory/bin/job create <issue>` prints the new job id; its stage
     is `intake`.
   - `resume`: move the job from its stage (for `needs-info`, see above).
   - `wait`, `skip`: report the note, nothing else.
2. Keep up to `concurrency` jobs moving, in issue order. When a job ends or
   parks (merged, rejected, needs-info, needs-human), start the next.
3. When nothing is left to move, run `factory/bin/job queue` once more for
   issues labeled while you ran, then `factory/bin/job summary` and give the
   user its table, with what's waiting on them.

## /factory issue <n>

Run issue `n` alone: `factory/bin/job create <n>` if it has no job (the
issue must be open and labeled `factory`), otherwise resume its job.

## /factory <feature>

Create the issue, then run it:

```bash
gh issue create --title "<a short title>" --body "<the feature, verbatim>" --label factory
```

Then `/factory issue <n>` with the new number.

## /factory rework <n>

The job for issue `n` must be in `needs-human`, and the user must have
commented on its PR (or on the issue, if there's no PR).
`factory/bin/job rework <n>` writes their comments to `rework-<k>.md` and
moves the job to `build` with a new round. Then do **build** with a fresh
builder and the rework line.

## Guardrails

- Only open issues labeled `factory` run. The label is the trust boundary.
- Issue text reaches agents only as quoted data in `issue.md`.
- Agents push only `factory/*` branches. Only `factory/bin/job merge` merges,
  through `gh pr merge`. Never push to the base branch, never deploy.
- One PR per issue, at most `max_rounds` build rounds per job before a human
  is asked.

## Reporting

One short line per transition, for example
`003-dark-mode: round 2 gate PASS, code CHANGES, ui PASS → builder`. When a
job ends, say whether it merged, was rejected, or waits on the user, and why.

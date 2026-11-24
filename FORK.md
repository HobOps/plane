# HobOps fork of Plane: maintenance guide

This repository is a fork of [makeplane/plane](https://github.com/makeplane/plane), the Community
Edition of Plane (AGPL-3.0-only). HobOps maintains it to run its own instance. It is not an official
Plane distribution and it is not affiliated with or endorsed by Plane Software, Inc.

The fork exists because the Community Edition lacks two things that instance needs:

- **Time tracking (worklogs).** Upstream has no model, API or UI for it.
- **An importer** that loads an existing workspace and keeps its authors, dates and work item
  numbers. The public API cannot set those fields.

Everything else is upstream's code, unchanged. `README.md` and the rest of the documentation in this
repository are upstream's and describe upstream's product.

## Policy

1. **Upstream release tags only.** A work branch starts from an upstream release tag, never from
   `preview`, upstream's default branch, which runs ahead of the releases.
2. **Minimal diff.** Only what upstream lacks and the instance needs goes in: worklogs (model,
   session API, an `api/v1` API and UI) and the importer. Anything else is proposed upstream or left
   out.
3. **Isolated backend.** The fork's backend code lives in its own Django app, `apps/api/plane/ext/`,
   with its own tables and migrations. Upstream models and migrations are not modified. The goal is
   that upstream's images can still run against the same database. Once an instance has applied one
   of the fork's migrations, that migration is never edited again; later changes get a new one.
4. **Every modified upstream file is registered** in the
   [ledger](#upstream-files-modified-by-this-fork), in the same pull request that modifies it. A pull
   request that changes an upstream file without a ledger entry is not merged.
5. **The worklog API is pinned by contract tests.** Clients written against Plane Cloud's worklog API
   must keep working: same routes (`issues/<id>/worklogs/`, `work-items/<id>/worklogs/` and
   `total-worklogs/`) and same fields. See [Worklog API](#worklog-api).
6. **No secrets and no real data.** This repository is public. Fixtures reproduce the shape of real
   API responses, never their content.

## Branches, tags and versions

| Ref | What it is |
| --- | --- |
| `hobops/v<upstream>`, today `hobops/v1.5.0` | The work branch for one upstream release: the upstream tag plus the fork's commits. The newest one is the default branch. |
| `v<upstream>`, today `v1.5.0` | The upstream release tag, pushed here unchanged. It is the base of the work branch. |
| `v<upstream>-hobops.N`, first `v1.4.3-hobops.1` | A fork release, cut from the work branch. Container images carry the same tag. |

The fork's whole diff is always one command away:

```sh
git diff --stat v1.5.0..hobops/v1.5.0
git log --oneline v1.5.0..hobops/v1.5.0
```

It is also at <https://github.com/HobOps/plane/compare/v1.5.0...hobops/v1.5.0>.

### Branch protection

The ruleset `hobops-release-branches` applies to every `hobops/*` branch and nobody bypasses it,
administrators included:

- Changes arrive through pull requests. No approvals are required, but the `api` and `web` checks of
  [`ci.yml`](#github-actions) are: they must pass on the pull request.
- Pull requests are merged with **squash** or **rebase**. Merge commits are disabled, so the fork's
  commits stay a linear series on top of the upstream tag.
- No force-pushes and no branch deletion. Old work branches stay: earlier releases were built from
  them.

Three things GitHub does that are easy to miss:

- **A rebase merge drops the signatures.** GitHub recreates each commit with the person who merged as
  committer, unsigned. The signed originals stay in the pull request, under `refs/pull/<number>/head`.
- **Pushing an open pull request's head commit straight to its base branch merges it.** GitHub accepts
  the push and marks the pull request as merged, because the commit already satisfies the rules. Merge
  with the button instead, so the merge method is the one the rules allow.
- **"Sync fork" is not how this fork follows upstream.** It offers to merge upstream's default branch,
  `preview`, which runs ahead of the releases. New upstream releases come in as described in
  [Moving to a new upstream release](#moving-to-a-new-upstream-release).

GitHub's "require linear history" rule is deliberately not used. Upstream's release tags point at
merge commits (`v1.4.3` and `v1.5.0` do), so that rule rejects creating a work branch at a tag.

## Moving to a new upstream release

```sh
git remote add upstream https://github.com/makeplane/plane.git    # once
git fetch --no-tags upstream tag v1.5.1

# 1. Publish the base: the upstream tag, unchanged, and a new work branch at it.
git push origin refs/tags/v1.5.1
git push origin 'v1.5.1^{commit}:refs/heads/hobops/v1.5.1'

# 2. Re-apply the fork's commits, oldest first, on a topic branch.
git switch -c bump/v1.5.1 v1.5.1
git -c merge.renameLimit=20000 cherry-pick -x v1.5.0..origin/hobops/v1.5.0
```

3. Resolve the conflicts, walk the ledger to check that every entry still applies, and run the tests.
4. Open a pull request from `bump/v1.5.1` into `hobops/v1.5.1` and merge it with **rebase**, so that
   each fork commit survives as its own commit.
5. Make `hobops/v1.5.1` the default branch and tag the release `v1.5.1-hobops.1`.

This was first done in full for v1.5.0 (2026-11). What that move taught:

- **Give git a high rename limit.** Upstream moved `apps/web/core/` up into `apps/web/`. With
  `merge.renameLimit` raised, the cherry-picks follow most of the moved files; the ones it loses show
  up as "deleted by us" and are re-applied by hand at the new path.
- **Drop the backports the new release already has.** Skip those commits in the cherry-pick and remove
  their ledger rows.
- **The fork's own frontend files use upstream's component library**, and upstream replaces it from
  time to time (v1.5.0 went from `@plane/ui` and `lucide-react` to `@makeplane/propel` and
  `@plane/blocks`). `check:types` lists what to port; a sibling upstream component shows the new idiom.
- **Prefer the place upstream now shares.** When upstream folds two modified files into one component,
  move the fork's change there and drop the old rows (the sidebar and the peek overview became
  `sidebar-sections.tsx`).
- **New upstream guards apply to the fork too:** the migrations lockfile has to list the fork's app,
  and new upstream workflows have to be removed.
- **Read the release's migrations before deploying.** Database migrations are not reversible, and the
  images of the previous release may not run on the migrated database.

## Upstream files modified by this fork

One row per upstream file, added by the pull request that modifies it. Inside the file, every modified
block starts with a comment that begins with `Fork (see FORK.md)`, so all of them can be found:

```sh
git grep -n "Fork (see FORK.md)"
```

| File | Why | Pull request |
| --- | --- | --- |
| `apps/api/plane/settings/common.py` | Registers the fork's Django app, `plane.ext`. | #2 |
| `apps/api/plane/urls.py` | Mounts the fork's routes: the session API (`plane.ext.urls`) under `api/` and the public worklog API (`plane.ext.api.urls`) under `api/v1/`. | #2, #6 |
| `apps/api/plane/bgtasks/issue_activities_task.py` | Worklog activity: handlers for created, updated and deleted entries, and their keys in the activity mapper. | #2 |
| `apps/api/plane/app/views/issue/activity.py` | Hides worklog activity from project guests in the issue history. | #2 |
| `apps/api/migrations_lockfile.txt` | Lists the fork's app, `ext`, with its latest migration. `makemigrations` writes the file and upstream's check compares it with the migration graph. | #11 |
| `apps/web/tsconfig.json` | The `@/plane-web/*` alias for the fork's frontend files in `apps/web/ce/`. | #2 |
| `apps/web/components/issues/issue-detail/issue-activity/root.tsx` | The "Log time" button next to the activity tabs, who can see worklogs and log time, and worklog entries in the "Activity" tab. | #2, #11 |
| `apps/web/components/issues/issue-detail/issue-activity/filter-root.tsx` | The worklog filter, shown only where worklogs can exist. The component becomes an observer. | #2 |
| `apps/web/components/issues/issue-detail/issue-activity/activity-comment-root.tsx` | Renders worklog entries in the activity feed. | #2 |
| `apps/web/components/issues/issue-detail/sidebar-sections.tsx` | The "Time Tracking" property of a work item. Upstream shares this component between the sidebar and the peek overview since v1.5.0; before, the fork changed `sidebar.tsx` and `peek-overview/properties.tsx`. | #2, #11 |
| `apps/web/components/project/project-feature-update.tsx` | Uses the fork's features list, which adds the time tracking toggle. | #2 |
| `apps/web/store/issue/issue-details/activity.store.ts` | Gives worklog activity its own activity type. | #2 |
| `packages/constants/src/issue/filter.ts` | The `WORKLOG` activity filter, selected by default. | #2 |
| `packages/types/src/project/projects.ts` | `is_time_tracking_enabled` in `IProject`. | #2 |
| `apps/web/app/(all)/[workspaceSlug]/(projects)/star-us-link.tsx` | The GitHub link points to this repository instead of upstream's: the [source code offer](#source-code-offer). | #4 |
| `packages/i18n/src/constants/namespaces.ts` | Registers `worklog`, the fork's i18n namespace. Its strings are in English and Spanish; other languages fall back to English. | #7 |
| `packages/types/src/settings.ts` | `features_time_tracking`, the project settings tab for time tracking. | #7 |
| `packages/constants/src/settings/project.ts` | That tab, under Features in the project settings. | #7 |
| `apps/web/components/settings/project/sidebar/item-icon.tsx` | The icon of that tab. | #7 |
| `apps/web/app/routes/core.ts` | The route of that tab's page. | #7 |
| `.github/workflows/` | Removed: all of upstream's workflows. In v1.5.0 they are `build-branch`, `check-version`, `codeql`, `copyright-check`, `feature-deployment`, `i18n-sync-check`, `migration-check`, `pull-request-build-lint-api`, `pull-request-build-lint-web-apps` and `react-doctor`. The fork's own `ci.yml` and `images.yml` are not upstream files. See [GitHub Actions](#github-actions). | #3, #11 |

Files that the fork adds are not upstream files and are not listed: this file, the
`apps/api/plane/ext/` app, the fork's own frontend files (`apps/web/ce/`, the time tracking settings
page in `features/time-tracking/` and the `worklog.json` i18n files) and tests.

## Code ported from Hangar

The worklog feature is ported from [Hangar](https://github.com/szymczag/hangar), another AGPL-3.0-only
fork of Plane: its pull requests [2](https://github.com/szymczag/hangar/pull/2),
[12](https://github.com/szymczag/hangar/pull/12) and [13](https://github.com/szymczag/hangar/pull/13),
as they stand on its `preview` branch at commit `d16a63297d63c0a300f86531b949b3cdd3c52626`
(2026-11-05). Nothing else is taken from Hangar.

- **Ported files keep Hangar's header**, unchanged: `Copyright (c) 2026-present Maciej Szymczak and
  contributors`, with `SPDX-License-Identifier: AGPL-3.0-only`.
- **Upstream files keep upstream's header**, modified or not: `Copyright (c) 2023-present Plane
  Software, Inc. and contributors`.
- **Files written for this fork** use `Copyright (c) 2026-present HobOps and contributors`, with the
  same SPDX line.
- **Commits say where the code comes from.** A cherry-pick keeps its original author and is made with
  `git cherry-pick -x`. A commit that copies code without its history names the Hangar commit in its
  message.
- **Changes are marked.** The license asks a modified version to say that it was modified and when
  (section 5a). Here that notice is this file, the ledger, the `Fork (see FORK.md)` comments and the
  pull request history.

Where Hangar's files mix worklogs with its other features (epics, issue types, SSO), only the worklog
parts are taken. Hangar's `apps/api/plane/ext/auth_urls.py`, an empty module for its SSO routes, is not
kept.

| Path in this repository | Origin in Hangar | Pull request |
| --- | --- | --- |
| `apps/api/plane/ext/__init__.py`, `apps.py`, `migrations/__init__.py`, `serializers/__init__.py` and `views/__init__.py` | Same paths. | [2](https://github.com/szymczag/hangar/pull/2) |
| `apps/api/plane/ext/models/__init__.py` and `apps/api/plane/ext/urls.py` | Same paths, with only the worklog entries. | [2](https://github.com/szymczag/hangar/pull/2), [12](https://github.com/szymczag/hangar/pull/12) |
| `apps/api/plane/ext/models/worklog.py`, `serializers/worklog.py` and `views/worklog.py` | Same paths. The fork adds `logged_at` and lowers the minimum to 0 minutes (#5). | [12](https://github.com/szymczag/hangar/pull/12) |
| `apps/api/plane/ext/migrations/0001_issue_worklog.py` | `apps/api/plane/ext/migrations/0003_issue_worklog.py`, without its dependency on Hangar's earlier `ext` migrations. The fork adds `logged_at` and the 0-minute minimum to it (#5), before any instance had applied it. | [12](https://github.com/szymczag/hangar/pull/12) |
| `apps/api/plane/tests/contract/app/test_worklog_app.py` | Same path. `test_duration_bounds` no longer treats 0 minutes as invalid, and the fork adds `TestWorklogCloudData` (#5). | [12](https://github.com/szymczag/hangar/pull/12) |
| `apps/web/ce/components/issues/worklog/`: `activity/root.tsx`, `activity/worklog-create-button.tsx`, `property/root.tsx` and `worklog-modal.tsx` | Same paths. The fork adds the date of the work and the 0-minute minimum, and moves the hardcoded English to the `worklog` i18n strings (#7). | [13](https://github.com/szymczag/hangar/pull/13) |
| `apps/web/ce/helpers/worklog.ts`, `apps/web/ce/hooks/use-worklogs.ts`, `apps/web/ce/services/worklog.service.ts` and `apps/web/ce/types/worklog.ts` | Same paths. The fork adds the work date helpers, `logged_at` and the 0-minute minimum (#7). | [13](https://github.com/szymczag/hangar/pull/13) |
| `apps/web/ce/components/projects/settings/features-list.tsx` | Same path. It wraps upstream's features list and adds the time tracking toggle, so it carries upstream's header, as in Hangar. A remark about Hangar's epics is removed from its opening comment, and its messages use the `worklog` i18n strings (#7). | [13](https://github.com/szymczag/hangar/pull/13) |

## Worklog API

The public API (`/api/v1/`, with an API key) serves worklogs with Plane Cloud's routes, fields and
responses, so a client written for Cloud, such as Plane's MCP server, only changes the host and the
key. Authentication and the per-key rate limit are upstream's. The contract tests in
`apps/api/plane/tests/contract/api/test_worklog_api.py` pin it.

| Route, under `/api/v1/workspaces/<slug>/projects/<project_id>/` | Methods |
| --- | --- |
| `issues/<issue_id>/worklogs/` and `work-items/<issue_id>/worklogs/` | `GET`: a list, newest first. `POST`: 201. |
| `issues/<issue_id>/worklogs/<id>/` and `work-items/<issue_id>/worklogs/<id>/` | `PATCH`: 200. `DELETE`: 204. |
| `total-worklogs/` | `GET`: a list of `issue_id` and `duration`, one per work item with worklogs, sorted by `issue_id`. |

An entry has Cloud's fields in Cloud's order: `id`, `created_at`, `updated_at`, `description`,
`duration`, `logged_at`, `created_by`, `updated_by`, `project_id`, `workspace_id` and `logged_by`.
As in Cloud:

- A `POST` without `logged_at` gets the day at 12:00 UTC, and one without `duration` gets 0 minutes.
- A negative duration is a 400, a project without time tracking a 404 and a work item that is not in
  the project a 403, with Cloud's messages.

Permissions are the session API's: project admins and members read and log time, guests and
non-members get a 403, and only the author or an admin changes or deletes an entry.

One difference from Cloud is deliberate: an entry cannot exceed 1,440 minutes, while Cloud accepts
longer ones. No Cloud entry is longer than 844 minutes.

## Source code offer

Plane is licensed under AGPL-3.0-only. Section 13 of the license requires that the users of a modified
version that runs on a network are offered its source code.

- **This public repository is that offer.** Every build that runs on the HobOps instance is built from
  a `v<upstream>-hobops.N` tag of this repository.
- **The instance points here.** The web app's GitHub link
  (`apps/web/app/(all)/[workspaceSlug]/(projects)/star-us-link.tsx`) points to this repository, and
  `images.yml` labels every image with the repository URL and the commit it was built from
  (`org.opencontainers.image.source` and `org.opencontainers.image.revision`). The workflow checks
  both the labels and the link before it finishes.
- Until the first fork release is deployed, the instance runs upstream's images, unmodified.

## GitHub Actions

Upstream's workflows come with the code (10 of them in v1.5.0) and are written for upstream's branches,
registries and infrastructure. None of them may run here:

- **Removed from the work branch**, with their ledger entry. Check again on every version bump: a new
  upstream release can bring new workflows, and they go before the bump is merged.
- **Not kept on any other branch.** The `preview` branch left over from creating the fork still carried
  them, so it was deleted on 2026-11-07; it was identical to upstream's `preview` at `618d0eb`. They
  had been disabled one by one before Actions was enabled, but GitHub forgets that setting once a
  workflow file leaves the default branch.
- **Blocked by the Actions settings.** Only GitHub's actions and `docker/*` are allowed, and only
  pinned to a commit. Upstream's workflows pin their actions to tags.

The fork's own workflows run on GitHub-hosted runners; HobOps' self-hosted runners are for private
repositories only. The default `GITHUB_TOKEN` is read-only, a job that needs more asks for it, and
every action is pinned to a commit.

| Workflow | Runs on | What it does |
| --- | --- | --- |
| `ci.yml` | Pull requests to `hobops/*` and pushes to them | `api`: ruff on the Python files the fork adds or changes, the migrations check (models and lockfile), `migrate` on an empty database and the whole backend suite, with Postgres, Valkey and RabbitMQ as services. `web`: lint and format of `web` and its packages, types of the four apps and the production build of `web`. The ruleset requires both jobs. |
| `images.yml` | Tags `v*-hobops.*`, or by hand | Builds the five images, `plane-backend`, `plane-frontend`, `plane-space`, `plane-admin` and `plane-live`, from the commit and pushes them to HobOps' private registry, `registry.hobops.io/hobops` (Harbor, with the `HARBOR_USERNAME` and `HARBOR_PASSWORD` repository secrets), all with the same tag and with the labels of the [source code offer](#source-code-offer). A tag publishes that release; a run by hand publishes `sha-<commit>`. |

### Building the images without GitHub Actions

Since 2026-11 Actions does not run on this repository, so `images.yml` cannot publish. The same five
images are built by hand with BuildKit, straight from a pushed commit, so nothing local goes in:

```sh
buildctl build --frontend dockerfile.v0 \
  --opt context=https://github.com/HobOps/plane.git#<full commit sha> \
  --opt filename=apps/web/Dockerfile.web --opt platform=linux/amd64 \
  --opt label:org.opencontainers.image.source=https://github.com/HobOps/plane \
  --opt label:org.opencontainers.image.revision=<full commit sha> \
  --opt label:org.opencontainers.image.version=<tag> \
  --opt label:org.opencontainers.image.licenses=AGPL-3.0-only \
  --opt label:org.opencontainers.image.title=plane-frontend \
  --output type=image,name=registry.hobops.io/hobops/plane-frontend:<tag>,push=true
```

- One build per row of the matrix in `images.yml`. `plane-backend` takes the subdirectory as context
  (`...#<sha>:apps/api`, `filename=Dockerfile.api`); the other four take the repository root.
- The tag follows `images.yml`: the release tag, or `sha-<first 7 of the commit>` for anything else.
- It runs unprivileged: the `moby/buildkit` rootless image with `buildctl-daemonless.sh` and
  `BUILDKITD_FLAGS=--oci-worker-no-process-sandbox`, as a Kubernetes Job with seccomp and AppArmor
  unconfined, and the registry credentials mounted as `~/.docker/config.json`. Each build needs about
  2 CPUs and takes 5 to 15 minutes.
- Without CI nothing checks a commit before it is built. Run by hand what `ci.yml` runs, and try the
  images on a scratch instance before deploying them.

## Conventions

- Commits are conventional commits (`type(scope): message`), in English.
- One logical change per pull request, with its ledger and provenance rows in the same pull request.
- Squash single changes. Use rebase when the individual commits must survive: ports that keep the
  original authorship, and version bumps.

## License

AGPL-3.0-only, the same as upstream (see `LICENSE.txt`). Changes made in this fork are published under
the same license.

HobOps adopted this policy on 2026-11-05 (internal ADR 0025).

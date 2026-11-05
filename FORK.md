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
   that upstream's images can still run against the same database.
4. **Every modified upstream file is registered** in the
   [ledger](#upstream-files-modified-by-this-fork), in the same pull request that modifies it. A pull
   request that changes an upstream file without a ledger entry is not merged.
5. **The worklog API is pinned by contract tests.** Clients written against Plane Cloud's worklog API
   must keep working: same routes (`issues/<id>/worklogs/`, `work-items/<id>/worklogs/` and
   `total-worklogs/`) and same fields.
6. **No secrets and no real data.** This repository is public. Fixtures reproduce the shape of real
   API responses, never their content.

## Branches, tags and versions

| Ref | What it is |
| --- | --- |
| `hobops/v<upstream>`, today `hobops/v1.4.3` | The work branch for one upstream release: the upstream tag plus the fork's commits. The newest one is the default branch. |
| `v<upstream>`, today `v1.4.3` | The upstream release tag, pushed here unchanged. It is the base of the work branch. |
| `v<upstream>-hobops.N`, first `v1.4.3-hobops.1` | A fork release, cut from the work branch. Container images carry the same tag. |
| `preview` | A frozen copy of upstream's default branch, left over from creating the fork. It is not used or updated, and nothing is based on it. |

The fork's whole diff is always one command away:

```sh
git diff --stat v1.4.3..hobops/v1.4.3
git log --oneline v1.4.3..hobops/v1.4.3
```

It is also at <https://github.com/HobOps/plane/compare/v1.4.3...hobops/v1.4.3>.

### Branch protection

The ruleset `hobops-release-branches` applies to every `hobops/*` branch and nobody bypasses it,
administrators included:

- Changes arrive through pull requests. No approvals are required today; the fork's CI checks become
  required when its workflows exist.
- Pull requests are merged with **squash** or **rebase**. Merge commits are disabled, so the fork's
  commits stay a linear series on top of the upstream tag.
- No force-pushes and no branch deletion. Old work branches stay: earlier releases were built from
  them.

GitHub's "require linear history" rule is deliberately not used. Upstream's release tags point at
merge commits (`v1.4.3` does), so that rule rejects creating a work branch at a tag.

## Moving to a new upstream release

```sh
git remote add upstream https://github.com/makeplane/plane.git    # once
git fetch --no-tags upstream tag v1.4.4

# 1. Publish the base: the upstream tag, unchanged, and a new work branch at it.
git push origin refs/tags/v1.4.4
git push origin 'v1.4.4^{commit}:refs/heads/hobops/v1.4.4'

# 2. Re-apply the fork's commits, oldest first, on a topic branch.
git switch -c bump/v1.4.4 v1.4.4
git cherry-pick v1.4.3..origin/hobops/v1.4.3
```

3. Resolve the conflicts, walk the ledger to check that every entry still applies, and run the tests.
4. Open a pull request from `bump/v1.4.4` into `hobops/v1.4.4` and merge it with **rebase**, so that
   each fork commit survives as its own commit.
5. Make `hobops/v1.4.4` the default branch and tag the release `v1.4.4-hobops.1`.

Step 1 is how `hobops/v1.4.3` was created. The other steps get their first real run with the next
upstream release.

## Upstream files modified by this fork

One row per upstream file, added by the pull request that modifies it. Inside the file, every modified
block starts with a comment that begins with `Fork (see FORK.md)`, so all of them can be found:

```sh
git grep -n "Fork (see FORK.md)"
```

| File | Why | Pull request |
| --- | --- | --- |
| _None yet_ | | |

Files that the fork adds are not upstream files and are not listed: this file, the
`apps/api/plane/ext/` app, and the fork's own frontend files and tests.

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

| Path in this repository | Origin in Hangar | Pull request |
| --- | --- | --- |
| _None yet_ | | |

## Source code offer

Plane is licensed under AGPL-3.0-only. Section 13 of the license requires that the users of a modified
version that runs on a network are offered its source code.

- **This public repository is that offer.** Every build that runs on the HobOps instance is built from
  a `v<upstream>-hobops.N` tag of this repository.
- **The instance must point here.** From the first fork release on, the web app's link to upstream's
  repository (`apps/web/app/(all)/[workspaceSlug]/(projects)/star-us-link.tsx` in v1.4.3) points to
  this repository, and the images are labeled with the repository URL and the commit they were built
  from (`org.opencontainers.image.source` and `org.opencontainers.image.revision`). That change
  belongs to the first fork release and gets its ledger entry.
- Until that release the instance runs upstream's images, unmodified.

## GitHub Actions

Actions is disabled for the whole repository. Upstream's workflows come with the code (9 of them in
v1.4.3) and are written for upstream's branches, registries and infrastructure. None of them may run
here.

The fork's own workflows (tests, builds and image publishing) arrive with the first fork release.
Before Actions is enabled:

- Upstream's workflows are neutralized: removed from the work branch, with their ledger entry, or
  disabled one by one. This is checked again on every version bump, because a new upstream release
  can bring new workflows.
- The fork's workflows use GitHub-hosted runners. HobOps' self-hosted runners are for private
  repositories only.

## Conventions

- Commits are conventional commits (`type(scope): message`), in English.
- One logical change per pull request, with its ledger and provenance rows in the same pull request.
- Squash single changes. Use rebase when the individual commits must survive: ports that keep the
  original authorship, and version bumps.

## License

AGPL-3.0-only, the same as upstream (see `LICENSE.txt`). Changes made in this fork are published under
the same license.

HobOps adopted this policy on 2026-11-05 (internal ADR 0025).

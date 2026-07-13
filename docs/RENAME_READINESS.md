# Repository Rename Readiness

Status: ready for an administrator-controlled rename from `Signal_Count` to
the exact target slug `signal-count`; the remote rename has **not** happened.
This receipt was prepared from `origin/main` at
`9c56a9c37eff975f9d09256e7de82e177accd2fd` on 2026-07-13.

## Evidence gate

The public-evidence gate required by the portfolio audit is satisfied for the
rename boundary:

- annotated tag object `98d9153018cbb5b34508fc1efc6f8df07f7e68a5`
  (`evidence-v0.1.0`) peels to the fixed evidence commit
  `9c56a9c37eff975f9d09256e7de82e177accd2fd`;
- evidence content address
  `sha256:0b1691ae31b574072e1bac0d52a375e1cae6329bccb82f1143bc18571fa3ef2e`;
- manifest SHA-256
  `6fbad30ebed357c81a17d38b27556df6b6a2fc9a6a65d65105c92428f17b8b5e`;
- exact-head PR CI run `29271808936` and post-merge run `29273423159`
  completed successfully, including tests, lint, format, dependency validation,
  and exact evidence reproduction.

This is credential-free synthetic fixture evidence. It is not evidence of
users, production operation, trading performance, model quality, protocol or
economic security, a remote AXL mesh, a real REE run, or a new testnet
transaction. The tag is evidence-only and the repository has no reuse license.

## Link and reference audit

The audit was run before this receipt was added:

- exact old-slug and owner/repository forms (`Signal_Count`,
  `ashishki/Signal_Count`, old GitHub web/clone/API URLs, and URL-encoded
  variants) have zero matches in the tracked current tree;
- the same forms have zero matches across all 88 commits reachable from local
  branches, remote-tracking refs, and tags;
- the remote advertises only `main`, server-managed `refs/pull/1/head`, and the
  annotated `evidence-v0.1.0` tag; `HEAD` resolves to `main`;
- a tracked-HEAD scan of 36 other local project repositories found zero inbound
  old-slug references. `telegram-research-agent` and `Demand-to-MVP-Radar` were
  deliberately excluded because active development there is paused from this
  audit scope;
- the root portfolio audit contains seven plain-text `Signal_Count` mentions as
  historical/planning records, not live links. The audit snapshot should remain
  immutable; completion belongs in its execution ledger;
- the Python distribution is already `signal-count`. Existing
  `signal_count_*` settings, environment variables, database filenames, and
  Python identifiers are runtime contracts, not repository URLs, and do not
  need a repository-rename migration;
- no current-tree badge, submodule, package registry, container image, Pages
  configuration, or citation embeds the old repository slug.

An authenticated repository lookup for `ashishki/signal-count` returned `404`
at the audit time, so the target appeared unoccupied. This is a point-in-time
observation, not a reservation; recheck it immediately before the mutation.

## Pre-rename and mutation checklist

1. Reconfirm the current local `origin/main` and GitHub `main` resolve to the
   same exact commit; record that current SHA, confirm its CI is green, and
   confirm the worktree is clean.
2. Independently verify that `refs/tags/evidence-v0.1.0` is still annotated tag
   object `98d9153018cbb5b34508fc1efc6f8df07f7e68a5` and that
   `evidence-v0.1.0^{}` still resolves to the fixed evidence commit
   `9c56a9c37eff975f9d09256e7de82e177accd2fd`. The evidence tag is not expected
   to move when `main` advances.
3. Recheck that `ashishki/signal-count` is unoccupied.
4. Create a full bundle and a sorted ref snapshot outside the repository; run
   `git bundle verify` and record both SHA-256 values before changing settings.
5. In GitHub repository settings, rename only `Signal_Count` to exact slug
   `signal-count`. Do not change visibility, default branch, history, tag, or
   release claims in the same operation.
6. Update local `origin` to `https://github.com/ashishki/signal-count.git` only
   after the setting change succeeds.
7. Verify the new web and clone URLs, old-URL redirect, default branch, full
   remote refs, tag object/peel, issue template, and a clean clone.
8. Rerun the complete CI/evidence gate on the renamed remote and bind the run ID
   to the unchanged or new exact commit.
9. Update this repository's README and this readiness/status receipt so they no
   longer say the remote is still `Signal_Count` or that the rename has not
   happened. Record the new URL, mutation time, exact refs, and post-rename CI.
10. Repeat the old-slug current-tree and inbound-reference scans. Update active
    portfolio/profile/umbrella links and the execution ledger; do not rewrite
    the dated strategy-audit snapshot.

## Rollback

If clone, redirect, Actions, ref, or tag verification fails, stop downstream
link changes. Rename the repository back to `Signal_Count` while that slug is
available, restore the old local `origin`, and rerun the same ref/tag/CI checks.
If GitHub cannot restore the repository directly, use the verified pre-rename
bundle and ref snapshot to recover under the original slug; never force-push
from an unverified or partial clone.

## Preparation validation

The receipt change was validated in an isolated worktree with the locked
dependency graph: `pip check`, 227 tests, Ruff lint, Ruff format over 126 files,
exact public-evidence reproduction, actionlint, and `git diff --check` all
passed. Seven repository-relative Markdown targets resolve inside the tree.
The Gensyn REE repository, explorer root, and three documented transaction URLs
each returned HTTP 200 during the point-in-time link check. No contract test was
added because this change does not alter a runtime or schema contract.

## Current blocker (EXT-002)

The execution environment has no authenticated GitHub CLI session: its bundled
`gh auth status` reports no logged-in hosts. The installed GitHub connector can
read the repository and create a pull request but exposes no repository-settings
rename operation. Therefore this change prepares and verifies the migration but
does not claim the remote was renamed. An authenticated settings-capable
credential or a repository administrator must execute checklist step 5.

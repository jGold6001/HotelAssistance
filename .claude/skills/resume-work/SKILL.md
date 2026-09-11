---
name: resume-work
description: Restore development context from the compact CURRENT.md checkpoint, verify it against live Git and source files, and identify the safest next step. Use only when explicitly invoked by the user.
disable-model-invocation: true
---

# Resume Work

Restore context with progressive disclosure. Do not load the project history wholesale.

## Live repository snapshot

- Branch: !`git branch --show-current 2>/dev/null || true`
- HEAD: !`git rev-parse --short HEAD 2>/dev/null || true`
- Working tree: !`git status --short 2>/dev/null || true`
- Recent commits: !`git log -5 --oneline --decorate 2>/dev/null || true`

## Procedure

1. Read `docs/work-reports/CURRENT.md` first.
2. Treat `CURRENT.md` as a navigation hint, not authoritative state.
3. Compare its branch, HEAD, and working-tree description with the live Git snapshot above.
4. If they differ, mark the checkpoint as stale and trust the repository.
5. Read only the files listed under `Relevant Files` that are necessary to verify the stated current state and next step.
6. Prefer source code, tests, configuration, and Git state over prose reports.
7. Do not read historical dated reports by default.
8. Read the `Source Report` referenced by `CURRENT.md` only when a material fact cannot be resolved from the repository or the checkpoint is internally ambiguous.
9. Read any older report only if the referenced source report explicitly points to it for a still-relevant unresolved decision.
10. Do not infer that unfinished work was completed. Verify before stating completion.
11. Do not modify code as part of context restoration unless the user also asked to continue implementation.

## Missing checkpoint fallback

If `docs/work-reports/CURRENT.md` does not exist or says no checkpoint has been recorded:
1. Do not scan all reports.
2. Find the newest dated report by filename.
3. Read only that one report.
4. Verify its claims against live Git and relevant source files.
5. Recommend running `/run-report` after the next work session so `CURRENT.md` is rebuilt.

## Output

Return a concise resume summary containing:
- current goal;
- verified repository state;
- any checkpoint mismatch or stale information;
- the primary next step;
- blockers or open questions that matter immediately.

Do not repeat the entire contents of `CURRENT.md` or the daily report.

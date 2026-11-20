# Action plan

Audited against upstream on 2026-11-20: olca-ipc.py master `6b8db74`, which
was released as olca-ipc 2.7.0 the same day (with olca-schema 2.7.0);
olca-modules tags v2.7.0 and v2.7.1; gdt-server master. The desktop app is
still at 2.7.0. Four issues are open and no pull requests.

## Where each issue stands

| Issue | State | What the code shows | What we do |
|---|---|---|---|
| [#38](https://github.com/GreenDelta/olca-ipc.py/issues/38) timestamps break `put()` | closed | Before olca-schema 2.2.2 the generator emitted `isoformat() + "Z"`, giving `+00:00Z`, which the Java parser rejects. Fixed in olca-schema `8a2ab4e` (2024-11-04). The current format parses fine (checked by compiling upstream `Json.parseDate`). | Nothing. Patch removed from olca-contrib. |
| [#5](https://github.com/GreenDelta/olca-ipc.py/issues/5) `find()` and duplicate names | closed | First-match behavior is documented in the API docs. Also #34, closed. | Keep `find_by` as a helper. No upstream PR. |
| [#41](https://github.com/GreenDelta/olca-ipc.py/issues/41) Monte Carlo memory | open | Server leak in `CalculationQueue.nextSimulation`. Fixed in olca-modules `c895e0e` (2026-11-03), included in the v2.7.1 tag. Desktop openLCA is still at 2.7.0. | Post the status comment. Our old chunked workaround was wrong; replaced. |
| [#4](https://github.com/GreenDelta/olca-ipc.py/issues/4) units get/find | open | msrocka's own issue; he called it "of course useful" on the forum. | Offer a PR after the first one lands. |
| (new) REST names | not filed | In 2.7.0: `RestClient.get(name=...)` loses names with `#` or `?`; `get_descriptor(name=...)` hits a route that does not exist. Tests fail on master. | Pull request, ready. |

Files in `upstream/`:

- `0001-Fix-names-in-the-REST-paths-of-the-RestClient.patch`, the commit
- `PR_rest_names.md`, title and description
- `COMMENT_issue_41.md`, the status comment
- `COMMENT_issue_4.md`, the follow-up offer

## Steps

### 1. Create the two repos (about a minute, on github.com)

1. Fork https://github.com/GreenDelta/olca-ipc.py with the default name.
2. Create an empty public repo `olca-contrib`, with no README, .gitignore,
   or license.

If you do this with Claude, say so and it pushes both. Otherwise:

### 2. Push olca-contrib

The folder is already a git repo with one commit and the `v0.4.0` tag.

```bash
cd olca-contrib
git remote add origin https://github.com/ASM-21/olca-contrib.git
git push -u origin main --follow-tags
```

### 3. Push the upstream fix to your fork

```bash
git clone https://github.com/ASM-21/olca-ipc.py.git
cd olca-ipc.py
git remote add upstream https://github.com/GreenDelta/olca-ipc.py.git
git fetch upstream
git checkout -b fix-rest-names upstream/master
git am /path/to/olca-contrib/upstream/0001-Fix-names-in-the-REST-paths-of-the-RestClient.patch
git push -u origin fix-rest-names
```

If `git am` reports a conflict, upstream has moved again. Run
`git am --abort` and ask Claude to rebase.

### 4. Open the pull request

GitHub shows a "Compare & pull request" banner on your fork after the push.
Base: `GreenDelta/olca-ipc.py` `master`. Head: `ASM-21/olca-ipc.py`
`fix-rest-names`. Paste the title and description from
`upstream/PR_rest_names.md`.

### 5. Comment on #41

Paste `upstream/COMMENT_issue_41.md`. It is independent of the PR and
useful on its own.

### 6. Later: #4

Once the PR gets a response, post `upstream/COMMENT_issue_4.md`. Write the
units PR in whatever shape msrocka asks for.

## How to work with this maintainer

The template is simonvanlierde's PRs #48 and #49, merged 2026-11-02:

- A greeting by first name, then a short list of concrete bugs.
- One commit per fix, with a message that says what was wrong and what
  changed.
- Tests in `tests/test_rest_paths.py` or `tests/test_ipc_errors.py` that
  need no server and fail on master.
- A plain statement of what was not tested.

msrocka merged #49 about 20 days after it was opened, without review
comments. Expect a similar wait, and bump politely after two weeks.

## Checks before posting anything

These came up in this audit and are worth repeating next time:

- Read the closing commit, not just the issue state. #38 looked open in an
  old summary; the fix had shipped two years ago.
- Run the upstream code. The first theory about #38 (Java rejects
  microseconds) was wrong, and a compiled test of the parser showed it.
- Check what a workaround actually frees. The chunked Monte Carlo idea
  looked plausible and leaked just as much.
- Re-fetch upstream right before pushing. msrocka committed to the same two
  files during this audit.

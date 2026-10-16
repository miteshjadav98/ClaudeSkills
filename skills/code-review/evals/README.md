# Validating the reviewer

## 1. The seeded-bug drill

`seeded-bugs/` holds a small FastAPI chat service before and after a change that adds RAG, a
tool-calling agent loop, history, and search. Twelve issues are planted, from P0 to Info, plus
five decoys that look like bugs but are not.

```bash
./seeded-bugs/setup.sh ~/review-drill      # builds a git repo: feat/rag-agent vs main
cd ~/review-drill && claude
> Use the code-reviewer agent to review feat/rag-agent against main
```

Then compare the review with `seeded-bugs/ANSWER_KEY.md`:

- **Recall** — at least 8 of the 9 main planted issues, including all of #1–#4
- **Precision** — zero decoys reported as new defects
- **Severity** — each within its accepted range
- **Verdict** — *Block merge pending critical fixes*

**As a learning drill:** review the diff yourself first, write your findings down, then run the
reviewer in quiz mode (`review this in quiz mode`) and score both of you against the key.

## 2. Against a real change

Pick a merged PR whose outcome you already know — ideally one that later needed a bug fix.

```bash
git checkout <commit-before-the-fix>
claude
> Review <the PR or commit that introduced the bug> with the code-review skill
```

Did it find the bug that later shipped? Did it flag anything that turned out to be fine? Keep a
short log of misses and false positives; they are the input for improving `references/`.

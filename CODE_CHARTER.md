# Code Charter

Global standards applied to **all code** I deliver, across every
project, from this point forward.

---

## A — Docstring Standard

- **Module docstring**: max 3 lines, state *what* not *why*.
- **Function docstring**: one-line summary; include `Args`/`Returns`
  only for non-obvious parameters.
- No analogies or comparisons in docstrings — those belong in the
  README, not in code.

## B — Comment Rules

- No comment that merely translates code to prose.
- Comments explain *why*, not *what*. If the code is self-evident,
  it gets no comment.
- Inline comments: max one line.

## C — Naming Convention

- Temporary variables: short and clear (`svc` not `db_service`,
  `p` not `policy_conflict`).
- No context-free names like `result`, `existing`, `response` —
  always qualify with context (e.g. `route_result`, `existing_policy`).

## D — Function Size

- Max 30 lines per function — refactor if exceeded.
- Helper functions are private (`_` prefix) and single-responsibility.

## E — Error Handling

- No bare `except`.
- Every exception is logged with sufficient context.
- HTTP errors live only in the API layer, never in the service layer.

## F — Import Order

- stdlib → third-party → internal, with a blank line between groups.
- No unused imports.

## G — Style

- Tone: senior dev — concise, no verbosity.
- Say it once. If the code shows it, don't repeat it in prose.

---

## Delivery Workflow

```
1. Design  (I describe, you approve)
        ↓
2. Implementation  (Charter applied)
        ↓
3. Automated tests  (run before delivery)
        ↓
4. Deliver zip
        ↓
5. Test on your system
        ↓
6. Git commit  (standard message)
        ↓
7. Git tag
```

## Scope

- This Charter applies to **all projects**, not just this one.
- Existing code is **not** retroactively refactored.
- A cleanup commit may land at the end of a project if warranted.
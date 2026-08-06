# Architecture

```text
rmlint.json
    |
    v
report parser
    |
    v
duplicate groups
    |
    v
keeper selection and manual overrides
    |
    v
reviewable plan
    |
    v
verification and quarantine
    |
    v
SQLite journal
    |
    v
restore
```

Optional preview providers may include `ffprobe`, `chafa`, ImageMagick, and
Poppler. Missing preview tools should not disable core safety functions.

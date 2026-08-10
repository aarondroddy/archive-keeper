# Usage

Preferred keeper order:

1. `/mnt/MyCloud1`
2. `/mnt/MyCloud2`
3. `/mnt/MyCloud3`

Analyze:

```bash
archive-keeper analyze
```

Generate a plan:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  plan
```

Open the reviewer:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  review
```

Before real use, verify the installed interface:

```bash
archive-keeper --help
archive-keeper quarantine --help
archive-keeper restore --help
```


## Restore collision verification

Restore checks an already-existing original against its quarantined copy with SHA-256. The comparison is bounded by `--verify-timeout` (30 seconds by default). Identical files can be reconciled during `--apply`; different-content collisions are skipped without overwriting either file.

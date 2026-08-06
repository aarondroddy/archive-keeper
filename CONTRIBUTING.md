# Contributing to Archive Keeper

Because Archive Keeper can move real files, filesystem changes require strong
testing and careful review.

## Development setup

```bash
git clone git@github.com:aarondroddy/archive-keeper.git
cd archive-keeper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## Run tests

```bash
python -m unittest discover -s tests -v
```

Changes involving quarantine, restore, mount checks, keeper selection, or the
journal should include both success and failure tests.

Prefer explicit, recoverable behavior. Avoid destructive defaults.

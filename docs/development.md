# Development and validation

The project matches the local Python/Poetry/Streamlit shape used by trade-bot while remaining a completely
separate personal repository.

## Canonical checks

```bash
make demo             # regenerate deterministic synthetic fixtures
make check            # Ruff, Black, mypy, pytest, native firmware policy tests, lock check
make firmware-hardware
make dashboard
```

Dashboard verification requires more than importing the Python module: start Streamlit, confirm an HTTP 200
response, and inspect all six pages for the normal, thermal anomaly, and ingress drill sessions. See
`docs/validation_report.md` for the most recent captured evidence.

## Privacy

The app reads local CSV/JSON files and has no network client, telemetry service, cloud storage, account token,
or analytics SDK. Imported sessions and annotations are ignored by Git. Synthetic fixtures are safe to commit.

## Repository identity

This checkout must use the personal SSH alias and identity:

```text
remote: git@github-personal:Jbultema/jarred_drive.git
name:   Jbultema
email:  Jbultema@users.noreply.github.com
```

Do not inherit a work identity and do not add work-library dependencies.

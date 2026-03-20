# Tests Layout

- `tests/core`: Core project smoke tests and integration checks that are not provider-specific.
- `tests/numbers`: Number-service unit tests and provider behavior tests.

## Run

```bash
pytest
```

Run a single area:

```bash
pytest tests/numbers
```

# dataops_client Package

Low-level HTTP client for the StreamflowOps REST API. This layer knows nothing about Dash, DataFrames, or water years — it speaks raw API.

## Key Files

- `client.py` — `DataOpsClient`: handles auth, retry, pagination, timeout
- `models.py` — Pydantic-like models: `Station`, `DischargeObservation`, `PullConfiguration`, `PaginatedResponse`
- `config.py` — client defaults (base URL, timeout, retry count)
- `exceptions.py` — `APIError`, `AuthenticationError`, `RateLimitError`, etc.
- `examples.py` — usage examples (not imported by the app)

## Rules

- Authentication is Bearer token via `DATAOPS_API_TOKEN`. Never embed the token in code.
- Retries use exponential backoff. Do not set retry count > 5 without consulting the API owner.
- Pagination is handled internally — callers receive a complete result set, not page chunks.
- This client is designed to be **standalone** (importable outside the dashboard). Keep its dependencies minimal: `requests`, `python-dotenv`, stdlib only.
- Do not import anything from `usgs_dashboard` or `dataops_adapter` here — this is the bottom of the dependency tree.
- If the API adds a new endpoint, add a method to `DataOpsClient` and corresponding models to `models.py`. Do not call `requests` directly anywhere outside this package.

# FX conversion tool

A cautious FastAPI tool for converting one currency to another using ECB rates
provided by Frankfurter. It returns either a verified rate or an explicit error,
never a made-up number.

## Run

Install the dependencies (Python 3.11+ recommended):

```bash
python3 -m pip install -r requirements.txt
./run.sh
```

The service listens on `PORT`, defaulting to `8080`. `FX_UPSTREAM_BASE` selects
the upstream host and defaults to `https://api.frankfurter.dev`; the application
adds `/v1` itself.

```bash
PORT=9000 FX_UPSTREAM_BASE=https://api.frankfurter.dev ./run.sh
```

Example request:

```bash
curl 'http://localhost:8080/tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28'
```

## Test

```bash
./test.sh
```

Tests use `httpx.MockTransport`, so they never contact the network. `test.sh`
also defaults `FX_UPSTREAM_BASE` to a closed local port as an additional guard.

## Endpoint behaviour

`GET /tools/convert` requires `amount`, `from`, `to`, and `date`.

- `amount` must be positive and have no more than two decimal places.
- Currency codes must have three letters and cannot be the same. Upstream
  rejection of an otherwise well-formed code is returned as `invalid_currency`.
- `date` must be ISO `YYYY-MM-DD` and cannot be in the future.
- A weekend or holiday request can receive the prior ECB publication returned
  by Frankfurter. `asked_date` remains the requested day while `rate_date` is
  the actual date from the upstream response; they are never conflated.
- Dates outside the published series return an error rather than a substituted
  rate.
- A successful dated quote is cached in memory by `(from, to, asked_date)`.
  Failures are not cached. This prevents repeat requests from calling upstream
  without allowing one date's quote to be reused for another date.
- Upstream timeouts, server failures, connection errors, and malformed payloads
  return an error response. They never produce `rate: 0` or `result: 0`.

## Error codes

| Error | HTTP status | Meaning |
| --- | --- | --- |
| `invalid_request` | 422 | A required query parameter is missing or malformed. |
| `invalid_amount` | 422 | Amount is not a positive finite decimal. |
| `invalid_amount_precision` | 422 | Amount has more than two decimal places. |
| `invalid_currency` | 422 | A code has the wrong form or is not supported upstream. |
| `same_currency` | 422 | Source and target are identical. |
| `invalid_date` | 422 | Date is not ISO `YYYY-MM-DD`. |
| `future_date` | 422 | Date is after today. |
| `rate_unavailable` | 422 | ECB has no rate in its series for that date. |
| `upstream_timeout` | 504 | The provider did not respond in time. |
| `upstream_unavailable` | 502 | The provider could not be reached. |
| `upstream_error` | 502 | The provider returned a server error. |
| `invalid_upstream_response` | 502 | The provider response was not usable. |

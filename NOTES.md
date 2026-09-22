# Notes

## Decisions

The service treats an incorrect rate as worse than no rate. A requested weekend
or holiday may receive the prior published ECB rate if Frankfurter supplies it,
but the response preserves both `asked_date` and the payload's `rate_date`.
Dates outside the series, invalid inputs, and unavailable or malformed upstream
data return an explicit non-2xx error. Successful historical quotes are cached
by currency pair *and requested date*; errors are not cached.

## With another day

I would add a bounded cache with metrics, per-key request coalescing rather than
a process-wide lock, structured logs with request IDs, and contract tests
against a separately running fake Frankfurter server. I would also confirm the
provider's exact conventions for unknown base currencies and map them more
precisely.

## AI tools

I used Codex to discuss the service boundary, scaffold the FastAPI/test
structure, and review edge cases. I checked the implementation by reading the
request/response paths and running the offline test script.

## One thing the AI got wrong

The first cache suggestion used only `(from, to)`. That would allow a rate for
one historic date to answer a request for another date. I caught it by tracing
two EUR/TRY requests with different dates and changed the key to include the
requested date and store the real rate date alongside the rate.

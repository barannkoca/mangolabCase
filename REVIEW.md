# Review of `tool.py`

## 1. Upstream failures become a false successful conversion

Every exception is caught and converted into a normal 200 response containing a
zero rate and zero result. A customer can be told that their money is worth zero
when the provider merely timed out or sent bad data. Verify by pointing
`UPSTREAM` at a closed port or returning a 500/non-JSON body, then checking that
the endpoint responds 200 with `rate: 0`.

## 2. The cache returns the wrong rate for a different requested date

The cache key contains only the currency pair. Once EUR/TRY is requested for
one date, every later EUR/TRY request uses that stored rate—even for a different
historic day—and reports the caller's requested date as the rate date. Verify
with two EUR/TRY requests for dates with different fake upstream rates.

## 3. It misrepresents the date of the rate, including weekends and holidays

`fetch_rate` returns `str(on or date.today())` instead of the `date` field in
the upstream payload. Its fallback asks `/latest` but still labels that rate as
the asked date. Verify with a Friday payload for a Sunday request and compare
`rate_date` with the upstream date.

## 4. Review/test configuration cannot replace the real upstream

`UPSTREAM` hardcodes the real Frankfurter host, contrary to the required
`FX_UPSTREAM_BASE` configuration. Review tests using a fake provider cannot
control it. Verify by setting `FX_UPSTREAM_BASE` to a local fake server and
logging the actual requested host; it remains `api.frankfurter.dev`.

## The one I would fix before shipping tonight

I would stop returning a fabricated 200/zero conversion first. It can create
the most immediately harmful customer statement during any provider incident.

## Things that look suspicious but are fine

Rounding the final `result` to two decimal places is appropriate for a
customer-facing money value. The defect is that the code also rounds the
*exchange rate* to two decimals before multiplying, which is separate.

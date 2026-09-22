"""A small, deliberately cautious currency-conversion HTTP tool."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Awaitable, Callable

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


MAX_AMOUNT_DECIMAL_PLACES = 2
LATEST_CACHE_SECONDS = 10 * 60
UPSTREAM_TIMEOUT_SECONDS = 5.0
logger = logging.getLogger("uvicorn.error")


class ConversionError(Exception):
    def __init__(self, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message


@dataclass(frozen=True)
class RateQuote:
    rate: Decimal
    rate_date: date
    expires_at: datetime | None


Transport = httpx.AsyncBaseTransport | None


def upstream_base() -> str:
    """Return the configured host, adding Frankfurter's versioned API path."""
    host = os.getenv("FX_UPSTREAM_BASE", "https://api.frankfurter.dev").rstrip("/")
    return f"{host}/v1"


def parse_amount(raw_amount: str) -> Decimal:
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation as exc:
        raise ConversionError(422, "invalid_amount", "Amount must be a positive decimal number.") from exc

    if not amount.is_finite() or amount <= 0:
        raise ConversionError(422, "invalid_amount", "Amount must be greater than zero.")
    if -amount.as_tuple().exponent > MAX_AMOUNT_DECIMAL_PLACES:
        raise ConversionError(
            422,
            "invalid_amount_precision",
            f"Amount may have at most {MAX_AMOUNT_DECIMAL_PLACES} decimal places.",
        )
    return amount


def parse_currency(raw_currency: str, field_name: str) -> str:
    currency = raw_currency.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ConversionError(422, "invalid_currency", f"{field_name} must be a three-letter currency code.")
    return currency


def parse_asked_date(raw_date: str) -> date:
    try:
        asked = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ConversionError(422, "invalid_date", "Date must use the YYYY-MM-DD format.") from exc
    if asked > date.today():
        raise ConversionError(422, "future_date", "Date cannot be in the future.")
    return asked


def is_fresh(quote: RateQuote) -> bool:
    return quote.expires_at is None or quote.expires_at > datetime.now(timezone.utc)


async def get_rate(
    *,
    cache: dict[tuple[str, str, str], RateQuote],
    transport: Transport,
    base_currency: str,
    target_currency: str,
    asked_date: date,
) -> RateQuote:
    cache_key = (base_currency, target_currency, asked_date.isoformat())
    cached = cache.get(cache_key)
    if cached and is_fresh(cached):
        logger.info(
            "rate_cache_hit from=%s to=%s asked_date=%s",
            base_currency,
            target_currency,
            asked_date.isoformat(),
        )
        return cached

    try:
        async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_SECONDS, transport=transport) as client:
            response = await client.get(
                f"{upstream_base()}/{asked_date.isoformat()}",
                params={"base": base_currency, "symbols": target_currency},
            )
    except httpx.TimeoutException as exc:
        raise ConversionError(504, "upstream_timeout", "Currency-rate provider timed out. Please try again.") from exc
    except httpx.HTTPError as exc:
        raise ConversionError(502, "upstream_unavailable", "Currency-rate provider is unavailable. Please try again.") from exc

    if response.status_code >= 500:
        raise ConversionError(502, "upstream_error", "Currency-rate provider could not complete the request.")
    if response.status_code == 404:
        raise ConversionError(422, "rate_unavailable", "No ECB rate is available for that date.")
    if response.status_code >= 400:
        raise ConversionError(422, "invalid_currency", "One of the currency codes is not supported.")

    try:
        payload = response.json()
        rate = Decimal(str(payload["rates"][target_currency]))
        rate_date = date.fromisoformat(payload["date"])
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ConversionError(
            502,
            "invalid_upstream_response",
            "Currency-rate provider returned an unusable response.",
        ) from exc

    if not rate.is_finite() or rate <= 0:
        raise ConversionError(502, "invalid_upstream_response", "Currency-rate provider returned an unusable response.")

    # A dated ECB quote does not change. Keep its real publication date too.
    quote = RateQuote(rate=rate, rate_date=rate_date, expires_at=None)
    cache[cache_key] = quote
    return quote


def create_app(*, transport: Transport = None) -> FastAPI:
    app = FastAPI(title="fx-tool", version="1.0")
    app.state.cache = {}
    app.state.transport = transport
    app.state.cache_lock = asyncio.Lock()

    @app.exception_handler(ConversionError)
    async def conversion_error_handler(_: Request, exc: ConversionError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_request", "message": "Required query parameters are missing or malformed."},
        )

    @app.get("/tools/convert")
    async def convert(
        amount: str = Query(...),
        from_: str = Query(..., alias="from"),
        to: str = Query(...),
        asked_date_raw: str = Query(..., alias="date"),
    ) -> dict[str, str | float]:
        parsed_amount = parse_amount(amount)
        base_currency = parse_currency(from_, "from")
        target_currency = parse_currency(to, "to")
        if base_currency == target_currency:
            raise ConversionError(422, "same_currency", "Source and target currencies must be different.")
        asked_date = parse_asked_date(asked_date_raw)

        # Lock prevents two concurrent identical calls from both missing the cache.
        async with app.state.cache_lock:
            quote = await get_rate(
                cache=app.state.cache,
                transport=app.state.transport,
                base_currency=base_currency,
                target_currency=target_currency,
                asked_date=asked_date,
            )

        result = (parsed_amount * quote.rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {
            "amount": float(parsed_amount),
            "from": base_currency,
            "to": target_currency,
            "rate": float(quote.rate),
            "result": float(result),
            "rate_date": quote.rate_date.isoformat(),
            "asked_date": asked_date.isoformat(),
            "source": "ECB via frankfurter.dev",
        }

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()

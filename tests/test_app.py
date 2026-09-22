import os
import unittest

import httpx

from app import create_app


VALID_PARAMS = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-30"}


class ConvertTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.requests: list[httpx.Request] = []
        os.environ["FX_UPSTREAM_BASE"] = "http://fake-upstream.test"

    def make_client(self, handler):
        def recording_handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        app = create_app(transport=httpx.MockTransport(recording_handler))
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tool.test")

    async def test_returns_actual_rate_date_and_uses_configured_upstream(self) -> None:
        def upstream(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "fake-upstream.test")
            self.assertEqual(request.url.path, "/v1/2026-08-30")
            self.assertEqual(dict(request.url.params), {"base": "EUR", "symbols": "TRY"})
            return httpx.Response(200, json={"date": "2026-08-28", "rates": {"TRY": 47.1234}})

        async with self.make_client(upstream) as client:
            response = await client.get("/tools/convert", params=VALID_PARAMS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "amount": 250.0,
                "from": "EUR",
                "to": "TRY",
                "rate": 47.1234,
                "result": 11780.85,
                "rate_date": "2026-08-28",
                "asked_date": "2026-08-30",
                "source": "ECB via frankfurter.dev",
            },
        )

    async def test_repeated_question_uses_cache(self) -> None:
        def upstream(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"date": "2026-08-28", "rates": {"TRY": 47.1234}})

        async with self.make_client(upstream) as client:
            first = await client.get("/tools/convert", params=VALID_PARAMS)
            second = await client.get("/tools/convert", params=VALID_PARAMS)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.requests), 1)

    async def test_rejects_invalid_input_before_contacting_upstream(self) -> None:
        async with self.make_client(lambda _: self.fail("upstream should not be called")) as client:
            negative = await client.get("/tools/convert", params={**VALID_PARAMS, "amount": "-1"})
            precision = await client.get("/tools/convert", params={**VALID_PARAMS, "amount": "1.123"})
            same_currency = await client.get("/tools/convert", params={**VALID_PARAMS, "to": "EUR"})
            future = await client.get("/tools/convert", params={**VALID_PARAMS, "date": "2099-01-01"})

        self.assertEqual(negative.json()["error"], "invalid_amount")
        self.assertEqual(precision.json()["error"], "invalid_amount_precision")
        self.assertEqual(same_currency.json()["error"], "same_currency")
        self.assertEqual(future.json()["error"], "future_date")
        self.assertEqual(self.requests, [])

    async def test_upstream_500_never_returns_a_fake_rate(self) -> None:
        async with self.make_client(lambda _: httpx.Response(500, json={"error": "broken"})) as client:
            response = await client.get("/tools/convert", params=VALID_PARAMS)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "upstream_error")
        self.assertNotIn("rate", response.json())

    async def test_bad_upstream_json_is_a_safe_error(self) -> None:
        async with self.make_client(lambda _: httpx.Response(200, content=b"not json")) as client:
            response = await client.get("/tools/convert", params=VALID_PARAMS)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "invalid_upstream_response")

    async def test_upstream_timeout_is_reported(self) -> None:
        def upstream(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow", request=request)

        async with self.make_client(upstream) as client:
            response = await client.get("/tools/convert", params=VALID_PARAMS)

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error"], "upstream_timeout")

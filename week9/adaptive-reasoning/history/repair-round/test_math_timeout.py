import asyncio
import unittest
from unittest.mock import AsyncMock

from math_timeout import generate_with_timeout


class SelectorTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_queued_timeout_aborts_only_that_request(self):
        engine = AsyncMock()
        result = await generate_with_timeout(engine, "selector", asyncio.sleep(1), timeout=0.01)
        self.assertIsNone(result)
        engine.abort.assert_awaited_once_with("selector")
        result = await generate_with_timeout(engine, "next", asyncio.sleep(0, result="4K"))
        self.assertEqual(result, "4K")

import asyncio


async def generate_with_timeout(engine, request_id, generation, timeout=30):
    try:
        return await asyncio.wait_for(generation, timeout)
    except asyncio.TimeoutError:
        await engine.abort(request_id)
        return None

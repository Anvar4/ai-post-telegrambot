import asyncio
import contextlib

from app.main import run

if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())

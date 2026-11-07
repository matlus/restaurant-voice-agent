import asyncio

from voice_agent_restaurant import __doc__ as _library_marker


async def run() -> None:
    _ = _library_marker


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

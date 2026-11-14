"""Call the running vwx-mcp server over streamable HTTP (live smoke test).

    uv run --with fastmcp==4.0.10 python tests/live_client.py ping
    uv run --with fastmcp==4.0.10 python tests/live_client.py list
    uv run --with fastmcp==4.0.10 python tests/live_client.py call <tool> '<json args>'

Needs the server on 127.0.0.1:8082 and Vectorworks with the bridge running.
"""

from __future__ import annotations

import asyncio
import json
import sys

from fastmcp import Client

URL = "http://127.0.0.1:8082/mcp"


async def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    async with Client(URL) as client:
        if cmd == "list":
            tools = await client.list_tools()
            print(f"{len(tools)} tools")
            for t in sorted(tools, key=lambda t: t.name):
                if len(argv) > 1 and argv[1] not in t.name:
                    continue
                print(f"  {t.name}")
            return 0
        if cmd == "ping":
            res = await client.call_tool("ping", {})
            print(_text(res))
            return 0
        if cmd == "call":
            if len(argv) < 2:
                print("usage: call <tool> '<json args>'")
                return 2
            args = json.loads(argv[2]) if len(argv) > 2 else {}
            res = await client.call_tool(argv[1], args)
            print(_text(res))
            return 0
    print(f"unknown command {cmd!r}")
    return 2


def _text(res) -> str:
    parts = []
    for block in getattr(res, "content", []) or []:
        parts.append(getattr(block, "text", str(block)))
    return "\n".join(parts) if parts else str(res)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))

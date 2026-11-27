"""Read-only HTTP smoke for monthly sales/Quality and existing MCP read tools.

DECIMUS_MCP_URL, DECIMUS_MCP_TOKEN are required. Optional MCP_SMOKE_COUNTRY,
MCP_SMOKE_MONTH (YYYY-MM), MCP_SMOKE_FORBIDDEN_COUNTRY (partner scope check).
No accounts or business records are created; no response data or tokens are printed.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit


def rpc(url: str, token: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("MCP smoke requires HTTP or HTTPS")
    request = urllib.request.Request(  # noqa: S310 — scheme checked above
        url,
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "decimus-business-smoke/1",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 — checked URL
        answer = json.load(response)
    if "error" in answer:
        raise RuntimeError("JSON-RPC request refused")
    return answer["result"]


def payload(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("isError"):
        raise RuntimeError("MCP tool refused the read")
    text = result["content"][0]["text"]
    if text.startswith("<untrusted_data "):
        text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
    return json.loads(text)


def require(condition: Any) -> None:
    if not condition:
        raise RuntimeError("MCP business smoke condition failed")


def main() -> None:
    url, token = os.environ["DECIMUS_MCP_URL"], os.environ["DECIMUS_MCP_TOKEN"]
    month = os.environ.get("MCP_SMOKE_MONTH") or (
        date.today().replace(day=1) - timedelta(days=1)
    ).strftime("%Y-%m")
    country = os.environ.get("MCP_SMOKE_COUNTRY")
    info = rpc(
        url,
        token,
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "decimus-business-smoke", "version": "1"},
        },
    )
    require(info["serverInfo"]["name"] == "decimus")
    tools = {t["name"]: t for t in rpc(url, token, "tools/list", {})["tools"]}
    expected = {
        "sales_summary",
        "quality_summary",
        "ratings_summary",
        "ratings_units",
        "ratings_unit_periods",
        "aggregators_status",
        "list_inspections",
        "get_inspection",
    }
    require(expected <= tools.keys())
    for name in ("sales_summary", "quality_summary"):
        require(tools[name]["annotations"]["readOnlyHint"])
        arguments: dict[str, Any] = {"month": month, "limit": 1}
        if country:
            arguments["country"] = country
        data = payload(rpc(url, token, "tools/call", {"name": name, "arguments": arguments}))
        require(data["status"] == "ok" and data["returned"] == 1)
        require(data["units"] and data["countries"])
        if country:
            require({r["country"] for r in data["countries"]} == {country})
        require("revenue" not in data)
        print(f"OK {name}: monthly data and pagination")
    for name in ("ratings_summary", "list_inspections"):
        result = rpc(url, token, "tools/call", {"name": name, "arguments": {}})
        require(not result.get("isError"))
        print(f"OK {name}: existing read path")
    forbidden = os.environ.get("MCP_SMOKE_FORBIDDEN_COUNTRY")
    if forbidden:
        for name in ("sales_summary", "quality_summary"):
            result = rpc(
                url,
                token,
                "tools/call",
                {"name": name, "arguments": {"month": month, "country": forbidden}},
            )
            require(result.get("isError"))
        print("OK partner country boundary: both tools refused foreign country")


if __name__ == "__main__":
    main()

"""Read-only, unauthenticated preflight of the official Viam MCP endpoint.

Run with: uv run python mcp_comparison/preflight.py
Does not load robot credentials, request OAuth authorization, or call robot tools.
The duration measures an authentication response, not a successful MCP operation.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ENDPOINT = "https://app.viam.com/mcp"
ROOT = Path(__file__).resolve().parents[1]


def main():
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "viam-hackathon-readonly-comparison", "version": "0.1"},
        },
    }
    request = Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    start = perf_counter()
    try:
        response = urlopen(request, timeout=15)
    except HTTPError as error:
        response = error
    with response:
        body = response.read().decode("utf-8", "replace")
        report = {
            "at": datetime.now(timezone.utc).isoformat(),
            "endpoint": ENDPOINT,
            "request": "Unauthenticated initialize; no machine tools called",
            "elapsed_ms": round((perf_counter() - start) * 1000, 1),
            "http_status": response.status,
            "www_authenticate": response.headers.get("WWW-Authenticate"),
            "body": json.loads(body),
            "authenticated_machine_latency_ms": None,
            "language_accuracy": None,
        }
    destination = ROOT / "artifacts/diagnosis/mcp-preflight.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

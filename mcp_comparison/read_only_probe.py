"""Use the authenticated official MCP via Codex; only read_machine_api is exposed.

Run: uv run python mcp_comparison/read_only_probe.py
Measures MCP call start/completion events, separate from model deliberation.
Never loads machine credentials or persists camera pixels.
"""
import json
import subprocess
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
MACHINE = "0ff1c3e0-d169-4194-a66e-8f854630ce99"


def main():
    config = tomllib.loads((Path.home() / ".codex/config.toml").read_text())
    args = [
        CLI, "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
        "--json", "-s", "read-only", "-m", config["model"],
        "-c", "model_reasoning_effort=" + json.dumps(config.get("model_reasoning_effort", "medium")),
        "-c", "features.shell_tool=false",
        "-c", 'mcp_servers.viam.url="https://app.viam.com/mcp"',
        "-c", 'mcp_servers.viam.enabled_tools=["read_machine_api"]',
        "-C", str(ROOT), "-",
    ]
    prompt = f"""This is an authorized read-only timing batch on Viam machine {MACHINE}.
Use only mcp__viam__read_machine_api, exactly six calls in this order, sequentially:
1-3: api=rdk:component:arm, resource_name=arm, method=GetEndPosition, request={{}}.
4-6: api=rdk:component:camera, resource_name=cam, method=GetImages, request={{}}.
Do not parallelize calls. Use no shell, files, browser, other MCP, or agents.
Do not move, stop, reset, configure, or call any other method. These methods only read.
Do not output images or raw payloads. No interpretation or movement task is requested.
If the first occurrence of a method fails, skip its other repeats and report the failure.
The machine already has its working API key. End with a short success/failure summary.
"""
    report = {"at": datetime.now(timezone.utc).isoformat(), "cli": CLI,
              "model": config["model"], "method": "Codex MCP call event timing",
              "machine_id": MACHINE, "calls": [], "errors": [],
              "no_motion_methods_exposed": True}
    started = {}
    begin = time.perf_counter()
    with subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True) as proc:
        proc.stdin.write(prompt)
        proc.stdin.close()
        for line in proc.stdout:
            elapsed = time.perf_counter() - begin
            event = json.loads(line)
            item = event.get("item", {})
            if event.get("type") in ("error", "turn.failed"):
                report["errors"].append(event)
            if item.get("type") != "mcp_tool_call":
                continue
            key = item["id"]
            if event["type"] == "item.started":
                started[key] = elapsed
            elif event["type"] == "item.completed":
                result = item.get("result") or {}
                blocks = result.get("content", [])
                row = {
                    "tool": item.get("tool"), "arguments": item.get("arguments"),
                    "start_seconds": round(started[key], 3),
                    "client_event_elapsed_ms": round((elapsed - started[key]) * 1000, 1),
                    "rpc_latency_ms": (round((elapsed - started[key]) * 1000, 1)
                                       if item.get("status") == "completed" and not item.get("error")
                                       else None),
                    "status": item.get("status"), "error": item.get("error"),
                    "is_error": result.get("isError", result.get("is_error", False)),
                    "image_count": sum(b.get("type") == "image" for b in blocks),
                    "text_chars": sum(len(b.get("text", "")) for b in blocks),
                }
                report["calls"].append(row)
                print(json.dumps(row), flush=True)
        report["returncode"] = proc.wait()
    report["total_seconds"] = round(time.perf_counter() - begin, 3)
    target = ROOT / "artifacts/diagnosis/mcp-readonly-timings.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(target), "returncode": report["returncode"],
                      "total_seconds": report["total_seconds"]}), flush=True)


if __name__ == "__main__":
    main()

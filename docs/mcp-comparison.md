# Official Viam MCP versus persistent SDK

Updated October 16, 2026 after the user connected MCP. **Viam MCP configuration
and authenticated metadata access now work.** Live robot reads were blocked by
the child Codex CLI's approval policy, not by OAuth or by the robot. The persistent
SDK remains the working execution path. A fair live-call latency or
language-accuracy comparison has **not** been completed.

## Observed result

- `codex mcp list --json` reports server `viam`, enabled, `auth_status=o_auth`,
  streamable HTTP at `https://app.viam.com/mcp`.
- This already-running parent chat did not acquire new native tool definitions.
  A fresh child using the app-bundled CLI did acquire the configured server.
- `mcp__viam__read_machine_metadata` succeeded for `armfarm21`, machine
  `0ff1c3e0-d169-4194-a66e-8f854630ce99`, main part
  `f3d9c05f-c163-47c5-8291-1f58f13e46f0` (`armfarm21-main`).
- `read_machine_api` attempts for arm `GetEndPosition` and camera `GetImages`
  both failed before reaching the machine: `MCP tool call requires approval,
  but approval policy is never`. The child CLI completed normally while
  reporting these individual tool failures.
- Their **1.5 ms / 0.2 ms client event durations are local rejection timings**,
  not robot RPC latency. No speed winner or language-accuracy winner is known.
- No robot API executed, no credentials were copied, and no key, cloud
  configuration, or global Codex configuration was changed. No process remains.

Current evidence: [`mcp-authenticated-preflight.json`](../artifacts/diagnosis/mcp-authenticated-preflight.json),
[`mcp-readonly-timings.json`](../artifacts/diagnosis/mcp-readonly-timings.json), and
[`native tool definitions`](../artifacts/diagnosis/mcp-discovery.txt).

The original unauthenticated 401 probe is retained only as historical evidence
in [`mcp-preflight.json`](../artifacts/diagnosis/mcp-preflight.json). It always
sends no token and therefore cannot check the newly configured OAuth login.

The read-only probe reuses that configured login and exposes only the native
`read_machine_api` tool; it does not bypass its approval requirements:

```sh
uv run python mcp_comparison/read_only_probe.py
```

Usable binary:
`/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`
(0.162.0-alpha.17.2). The shell's older npm `codex` (0.144.5) rejected the configured
`gpt-6-astra` model before any tool call. The probe uses the existing model and
reasoning defaults, a read-only sandbox, disabled shell, ephemeral session, and
per-command MCP settings; it edits no global configuration. The remaining step
is an ordinary supported client approval for the exact live read operations.

## What the official interfaces provide

Viam documents OAuth for MCP and tools for fleet/configuration reads,
world-state reads, live API calls, and `DoCommand`. Live reads use the machine's
default API key and can create it if missing, which is why the client does not
treat those tools as automatically read-only. Their descriptions and complete
input schemas were obtained from the authenticated connector; the public tool
list alone does not provide the full method coverage.
[Official MCP reference](https://docs.viam.com/reference/mcp/)

| Need | Persistent Python SDK | Official MCP status in this experiment |
| --- | --- | --- |
| Discover resources and state | Existing client methods | `read_machine_metadata` passed; `read_part_status` and machine-level `read_machine_api` available |
| Capture a camera image / native vision | Camera and vision APIs | `read_machine_api` explicitly supports `GetImages` and `CaptureAllFromCamera`; live call blocked by client approval |
| Read arm or gripper pose | Arm / robot / motion APIs | `GetEndPosition` attempted but approval-blocked; `get_world_state` reports frame poses, `TransformPose` is documented through `read_machine_api` |
| Preview a motion | Existing native planner path | No dedicated preview tool; exact native planner command still unverified |
| Execute a planned movement | Existing motion API path | `call_machine_api` accepts structured mutation RPCs; no movement tested |
| Preserve grasp/lift/place session | Long-lived local client | `call_machine_api` says each call's session ends on return; sustained multi-call holding is unverified |

Native `read_machine_api` takes `machine_id`, `method`, optional `api`,
`resource_name`, `part_name`, and protobuf-JSON `request`. Only unary methods are
supported. Images are returned as visible attachments, scaled to at most 1568 px
on a side; raw/depth frames are not rendered. Remaining response JSON must fit
64 KB, and point clouds are refused. This is a material difference from our
current SDK's point-cloud grasp perception.

`call_machine_api` accepts the same argument shape for mutating RPCs; it executes
immediately with no separate preview. `run_docommand` accepts `machine_id`,
`resource_name`, `command`, and optional `api`/`part_name`. It could expose a
model's read-only planning command, but such a command must be verified rather
than assuming every `DoCommand` is a preview. Neither mutation tool was called.

Viam's agent guide specifically identifies the SDK as suitable for stateful
grasp/lift/place sequences, streaming, and loops. The MCP connection is held in
Viam's cloud; the local SDK opens its own connection. Both reach the underlying
machine APIs, but MCP does not expose all SDK/CLI methods. The guide recommends
observing, transforming camera observations into the robot's frames, planning
with the motion service, and verifying by observation. This supports the main
implementation's single persistent client and scene-aware command execution.
[Official agent guide](https://docs.viam.com/build-apps/use-viam-from-an-agent/)

## Minimal fair comparison once live reads are approved

Use the same machine, model, model settings, instructions, scene image, and saved
scene/history facts. Test one path at a time. Begin with authenticated tool
discovery and read-only pose/camera calls. Compare cold connection separately
from repeated calls over a retained connection; record each sample and summarize
median and range. Do not compare the 401 response above against SDK RPC latency.

For language checks, use identical inputs on both routes and inspect the proposed
command sequence without moving hardware:

1. Move this red block slightly right.
2. Move the red block left by 5 cm.
3. Return the red bin to its previous state.
4. Move the yellow bin closer to the red bin.
5. Request an absent, ambiguous, or ungraspable object.

Score object identity, coordinate reference, displacement/relationship, prior
state use, observation requests, and correct refusal independently. The model
and the information it receives determine language interpretation; a different
transport by itself is not evidence of greater intelligence. Synthetic language
cases do not establish grasping capability: only the current carton grasp has
physical validation here.

Recommendation: continue the persistent SDK milestone. Keep the authenticated
MCP route available for agent interaction, but complete an approved live-read
comparison before claiming a latency benefit. Keep gripper-held sequences in the
existing persistent executor unless MCP session behavior is validated. No custom
MCP bridge or second robot controller is needed merely to compare the routes.

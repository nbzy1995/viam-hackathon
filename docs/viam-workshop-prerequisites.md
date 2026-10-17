# Viam workshop prerequisites

Reviewed 2026-10-16. Research only; these notes do not establish the physical station's current state.

## Before Phase 1

The workshop expects an xArm6, uFactory finger gripper, wrist-mounted RealSense D435, and System76 Meerkat running the Viam server. It requires a Viam account with an online machine; confirm its green Live indicator. Python 3.10+, a terminal, and the Viam Python SDK are needed for the later scripts; the documented validation is due before Phase 4. The companion repository is not needed to begin. [Workshop introduction](https://docs.viam.com/tutorials/pick-and-place/)

If the station is already provisioned, use that machine. Otherwise, the setup guide creates a machine inside a location in the Viam app, then uses Install to launch the setup wizard on the appropriate compute device. [First-machine setup](https://docs.viam.com/set-up-a-machine/first-machine/)

## What runs where

The cloud stores configuration. On the robot computer, viam-agent supervises viam-server; viam-server runs the resources and exposes their control APIs. Laptop Python code connects to that server. The browser Control tab also sends control calls to the server. Thus installing the Python SDK on the laptop does not provision the robot server. [Phase 1](https://docs.viam.com/tutorials/pick-and-place/platform-mental-model/)

## Exact Phase 1 configuration

On the intended live machine, open Configure, add a Block, search xArm6, select ufactory/xArm6, and name it `arm-1`. Its full model is `viam:ufactory:xArm6`. Attributes:

```json
{
  "host": "REPLACE_WITH_CONTROLLER_IP",
  "speed_degs_per_sec": 30
}
```

Use the actual controller address from the control-box label, not the laptop address. Save, then inspect Logs for module download/start and `arm-1` online. Phase 1 requires no script and does not ask for a deliberate move. [Phase 1](https://docs.viam.com/tutorials/pick-and-place/platform-mental-model/)

The server host must reach the controller. The module documents direct Ethernet with a same-subnet host address and default controller TCP port 502. Its sample addresses are examples, not this station's verified settings. [Module documentation](https://github.com/viam-modules/viam-ufactory-xarm#networking)

## Initialization matters

The reviewed driver constructor calls `x.start(ctx, false)`, and that function enables servos and sets motion mode and state. Saving an arm configuration can therefore affect the physical controller even without clicking a move button. This code inspection does not prove automatic homing or guarantee absence of motion; the deployed module version is unknown. Confirm the physical station is ready before saving. [Constructor](https://github.com/viam-modules/viam-ufactory-xarm/blob/89ff06a4f83d9670cb95080e7bc2c51bd923073a/arm/xarm.go#L585), [startup implementation](https://github.com/viam-modules/viam-ufactory-xarm/blob/89ff06a4f83d9670cb95080e7bc2c51bd923073a/arm/comm.go#L383-L411)

Phase 2 explicitly requires a clear workspace and accessible e-stop before moves, with small changes to one joint at a time. It adds gripper and camera resources and their frames. Its frame offsets apply to the workshop's specific mounting arrangement; different hardware requires measured offsets. These are later steps, not Phase 1 prerequisites. [Phase 2](https://docs.viam.com/tutorials/pick-and-place/configure-resources/)

## Verified team setup

Read-only inspection of the [assigned machine](https://app.viam.com/machine/0ff1c3e0-d169-4194-a66e-8f854630ce99/control?org=6d6c7293-bc67-43e4-9c8b-31c76aac27d3) on 2026-10-16:

- `armfarm21` / `armfarm21-main`: Online / Live, linux/amd64.
- Existing `arm`: ufactory/xArm6, module 1.1.36, Ready; joint positions returned, Idle, zero displayed arm error logs.
- Configured host `192.168.1.203`; speed 60 degrees/second; collision_sensitivity 0; use_urdfs true.
- Hardware comes from `ufactory-xarm6-realsense` fragment. Existing names are `arm`, `cam`, `gripper`, not the tutorial's names ending in `-1`. All three showed Ready in Control.
- Existing obstacle resources: table, wall-front, wall-side, ceiling. Their physical correctness has not been checked.
- No machine configuration changed and no motion commands sent.
- Laptop root `.venv` created using uv: Python 3.13.7, viam-sdk 0.84.0. Imports of viam, RobotClient, and Arm passed. Environment size 33 MB. This does not establish a Python connection to the robot.

Before proceeding: reconcile speed with the tutorial's 30 degrees/second, ask the station owner about disabled hardware collision detection, and confirm physical readiness/e-stop. Module source inspection above is not a version-matched audit of deployed 1.1.36. Camera model and frame calibration still need verification in Phase 2.

# End-to-end simulation scope and available paths

Inspected 2026-10-16. This document records capability and isolation evidence,
not a claim that an end-to-end run passed.

## Selected immediate evaluation path

Use the production `TextController`, real interpreter, native Viam planning,
production seven-stage transfer controller, and verification/history logic.
`tabletop_sim.py` substitutes local arm/gripper state and synthetic observations.
The only callback allowed to reach the existing Viam server is the read-only
`MotionClient.do_command({'plan': ...})` path. All actuator handles are replaced
within a process-local context. No simulated execution calls the real arm,
gripper, or saved-pose switches.

Object outcomes come from independent forward kinematics and local state:
grasp requires the simulated TCP to intersect an object's grasp region, carrying
updates the object's position from its attachment transform, and release settles
it vertically onto the table or support underneath. The adapter receives no user
request, task command, expected target, or evaluation answer. A native preview
path is applied locally; subsequent observations are generated from that changed
world state. Hidden objects remain in the simulated world. Extra obstacles and
hidden objects are supplied to native planning independently of model inputs.
The adapter applies the checked preview path rather than calling native
`Motion.Move`, so execution-time replanning inside that RPC and its controller
behavior are not covered. This avoids both physical actuation and silently
testing a different inverse-kinematics result from the preview.

Call this **stateful kinematic end-to-end integration**, not physics simulation.
It covers language-to-action/controller integration, native reach/collision
rejections, sequencing, overview recovery, local gripper state, post-action
verification, and history. It does not validate sensor images or segmentation,
depth noise, real camera calibration, friction, contact forces, object tipping,
deformation, grasp force, motor dynamics, or physical emergency stopping. Fixture
camera axes are explicit synthetic calibration; the production path still uses
calibrated camera transforms. Final physical success remains a separate gate.

The adapter has isolated fault hooks for camera, overview camera, planner,
before-execution observation, grasp, release, and post-release verification.
Faults have named events and occurrence counts; an expected late-stage failure
must not receive credit if an earlier stage prevented reaching that fault.

## Official Viam fake/simulated components

Viam's official fake arm supports xArm6 kinematics and reports joint state.
The version-matched source also offers `arm/simulated` timed joint movement and
custom model paths. Neither model supplies object contact or camera rendering.
The built-in fake gripper's `Grab` returns false and `IsHoldingSomething` always
reports false, so the current transfer controller cannot complete with it alone.
[Arm documentation](https://docs.viam.com/hardware/common-components/add-an-arm/),
[v1.12.0 fake arm source](https://github.com/viamrobotics/rdk/blob/v1.12.0/components/arm/fake/fake.go),
[simulated arm source](https://github.com/viamrobotics/rdk/blob/v1.12.0/components/arm/sim/sim.go),
[fake gripper source](https://github.com/viamrobotics/rdk/blob/v1.12.0/components/gripper/fake/gripper.go).

A standalone local `viam-server` is an isolation improvement if the existing
server becomes unavailable. Use an explicit localhost configuration with no cloud
credentials, remotes, real hardware drivers, jobs, or triggers, and the saved
xArm/tool/wall geometry. It can supply genuine native planning and simulated arm
state, but the same synthetic object/perception adapter is still necessary.
Viam officially documents macOS Homebrew installation and local config files.
[Installation reference](https://docs.viam.com/operate/reference/viam-server/manage-viam-server/),
[standalone dummy config](https://github.com/viamrobotics/rdk/blob/v1.12.0/etc/configs/fake.json).

Read-only local checks found arm64 macOS 26.5.2, 22 GiB free, and a native
`/opt/homebrew/bin/brew` despite PATH resolving `/usr/local/bin/brew` first.
The current official v1.12.0 arm64 Tahoe bottle is 28,571,219 bytes (27.2 MiB),
verified with an authenticated public GHCR HEAD request; no package was downloaded.
Its native dependencies (`nlopt-static`, `ffmpeg`, `jpeg-turbo`, `opus`, `x264`)
are absent under that Homebrew prefix, so total installation size exceeds the
server bottle and has not been measured. No server or package was installed.
[Current official formula](https://github.com/viamrobotics/homebrew-brews/blob/main/Formula/viam-server.rb).

## Viam-hosted Isaac Sim

The configured Viam MCP `start_simulation` contract states that it starts an
Isaac Sim sandbox running `viam-server` **as the selected machine part**, using
that part's saved configuration. It is billed per minute, can take minutes to
become online, and may have no lifetime limit on Runpod. `stop_simulation` cannot
stop a still-pending sandbox. The callable contract gives no dollar rate.

That contract alone does not establish a separate shadow connection for an
already running physical part, automatic substitution of the physical arm/camera,
or an API to seed/reset our table, carton, colored objects, and gripper contacts.
No verified public Viam guide for those setup details was found in this pass.
Therefore do not start it against the physical arm's part. A credible next step
requires an isolated simulation-only machine/part, confirmed simulation resource
models and scenario reset API, explicit cost bound, and verified endpoint routing.
No hosted simulation was started and no paid resource was created.

Isaac Sim itself supports rigid-body physics and simulated sensors, but the
official platform requirements are Linux or Windows; this Mac is not a supported
local Isaac runtime. A native SDK workflow still needs a Viam simulation bridge
and an authored/calibrated scene. This is additional infrastructure, not a quick
replacement for the current checks.
[Official Isaac Sim project](https://github.com/isaac-sim/IsaacSim).

## What would establish physics end-to-end coverage

A physics gate must run the same text controller through the Viam API into a
contact-based gripper/arm model, render new RGB/depth observations from the moved
camera and objects, run the actual vision services on those observations, and
grade final poses/relations independently from simulator ground truth. Test
object mass/friction/placement variation and failed grasps as well as successful
transfers. A scripted attachment or copied expected target cannot establish that
gate. The present kinematic adapter deliberately makes no such claim.

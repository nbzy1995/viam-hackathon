# Table marks inspection — 2026-10-16

Task: identify and record the user's two marked table locations, then test an A-to-B transfer.

## Observed

Source: live Viam UI for armfarm21, machine 0ff1c3e0-d169-4194-a66e-8f854630ce99, inspected around 12:20 PM America/New_York.

- Machine Online; arm resource Failed; gripper resource Failed; camera resource Ready.
- Arm resource logs repeatedly report `resource build error: rpc error: code = Unknown desc = xArm: Servo motor 2 error;`. A visible entry was dated 12:19:40 PM, with repeated entries extending back at least to 12:10:02 PM.
- Arm configuration still shows host 192.168.1.203, speed_degs_per_sec 60, collision_sensitivity 0, use_urdfs true; module 1.1.36.
- Color camera feed reports roughly 1 frame/second. Inspected upper and lower portions show a largely featureless gray surface and small dark features at the bottom edge. Neither table mark could be identified confidently. This does not establish that the marks are absent from the table.
- Camera Screenshot button was clicked once; the browser download wait timed out. No saved image file was confirmed.

## Result

- A and B image locations: unverified.
- A and B robot-frame coordinates and grasp poses: unverified; no values recorded or invented.
- Motion test: not run because the arm reports a servo fault and target poses are unverified.
- No arm/gripper movement, fault-reset, or machine configuration changes were issued.

## Required next step

Have the on-site Viam staff inspect the reported servo motor 2 fault and restore the arm to Ready. Once the hardware is healthy, obtain a view showing both marks and establish their robot-frame poses, or teach the fixed poses directly using the official static-position procedure. Resolve the previously noted speed and collision-sensitivity settings before movement.

## Recovery investigation — around 12:40 PM

The user authorized moving the wrist camera to locate two blue markers and investigating a reset if the fault persisted.

- Rechecked the live UI: arm still Failed, with repeated servo motor 2 errors through 12:40:11 PM.
- Executed the documented read-only diagnostic `{"get_error": true}` from Configure > arm > Test > DoCommand.
- Result: `ConnectError: [unknown] resource rdk:component:arm/arm not available; reason=resource build error: rpc error: code = Unknown desc = xArm: Servo motor 2 error;`.
- The diagnostic could not reach the arm resource. Its normal DoCommand reset route is therefore unavailable in this state. No reset or movement command was issued.
- Official UFACTORY controller-code documentation identifies controller error 12 as Servo motor 2 error. This identifies the affected joint, not the detailed servo fault subtype.
- UFACTORY Studio's error-handling manual specifies power-on recovery for controller codes C11–C17. A configuration/factory reset is not its prescribed remedy for this fault class.
- Reviewed the installed module's v1.1.36 source: it supports `clear_error`, but that command requires an available arm resource. Restoring a guessed configuration would not establish physical fault recovery.

Sources: [UFACTORY error-code definitions](https://docs.api.ufactory.cc/zhHans/websocket_api/2.xarm_api_code.html), [UFACTORY error handling](https://docs.ufactory.cc/user_manual/ufactoryStudio/12.error_handling.html), [Viam module error handling](https://github.com/viam-modules/viam-ufactory-xarm#error-handling), [v1.1.36 driver](https://raw.githubusercontent.com/viam-modules/viam-ufactory-xarm/v1.1.36/arm/xarm.go).

Next action requires the on-site operator/staff to perform the manufacturer's controller power-cycle/re-enable procedure with the workspace clear. Then recheck Ready status, establish a safe observation pose, locate both blue marks, and teach/verify A and B before the transfer test. Machine configuration, obstacle geometry, and calibration remain unchanged.

## Follow-up live check

The machine page still shows Online with arm Failed. Latest displayed arm log: 2026-10-16 12:41:15 PM, `xArm: Servo motor 2 error;`. The existing DoCommand diagnostic output still reports the arm resource unavailable. Rechecked the official UFACTORY error-handling manual: C11–C17 recovery is power on again. No motion or default-configuration reset was issued; on-site recovery remains required.

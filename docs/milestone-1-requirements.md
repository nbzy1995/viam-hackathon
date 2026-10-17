# Milestone 1: Move one object from A to B

## Agreed scope

- The broader project is workspace restoration.
- The first milestone involves one object and two positions: move the object from A to B.
- A and B are fixed, marked locations. Before each run, the operator places the object at A in the same position and orientation.
- Use an easy-to-grasp object compatible with the existing gripper; no additional machinery or custom end-effector is required.
- Clarify requirements before choosing the approach; prefer the simplest approach supported by official Viam documentation.
- Ask the user only critical questions; decide routine details using simple defaults.

## Working defaults

These are simple defaults selected for this milestone, rather than additional user-confirmed requirements:

- One manual start command runs one complete pick-and-place cycle.
- The arm picks up the object at A, carries it clear of the table, sets it down at B, releases it, and withdraws to its starting pose.
- B is an outlined target area sized for the chosen object. Success means the object rests entirely inside that area; final orientation is unconstrained.
- Superseded by the updated round-trip scope below: the robot returns the object to A.
- Original working default: three consecutive cycles. Current evidence is one successful automatic round trip; three-cycle reliability is not claimed.
- A reported motion or grasp failure ends the sequence without an automatic retry. Physical emergency stop remains available to the operator.
- Voice interaction, visual localization, scene memory, and automatic visual success verification are deferred.
- No speed target for this milestone.

## Conceptual approach

Follow Viam's static pick-and-place progression: teach and verify fixed arm poses, then run those moves and gripper actions in order from a small Python script. Use the existing resource names `arm` and `gripper`. Validate the motion service's obstacle geometry against the actual station before execution.

Sequence: start -> above A -> grasp at A -> lift -> above B -> lower and release at B -> withdraw -> start.

The tutorial releases over a bin; placing onto a marked tabletop area requires teaching a suitable set-down pose and withdrawal instead. This is an adaptation to our milestone, not a claim that the tutorial directly specifies tabletop placement.

## Current physical evidence

One manual carton transfer from the relocated A to B succeeded, followed by
withdrawal and home return. The runtime script uses 3 degrees/second and
6 degrees/second squared. All six poses are saved. A is the relocated pickup
used during that transfer, not the original distant tape location.

The scripted cycle and repeatability acceptance remain unverified. See
`tutorial-checkpoints.md` for current evidence and limitations.

## Official reference

[Viam Phase 3: Static positions and obstacles](https://docs.viam.com/tutorials/pick-and-place/static-positions/) starts with saved poses to establish a working pick-and-place sequence before adding perception. This supports the agreed fixed-location scope.

## Updated scope: automatic round trip

The user now requests one trigger for A -> B -> A without intervention, using
native Viam controls and minimal infrastructure. The sequence places at B,
re-grasps without withdrawing, returns and places at A, then returns home.
The agent chooses reachable positions using the current carton location;
the user does not need to align it to the earlier taught A.

Current A cap/grasp center: (451.3, -509.0) mm, flange grasp height 320 mm.
Current B placement center: (391, -349) mm, flange height 323 mm.
A's 450, 410 and 390 mm approaches were unreachable; a 370 mm approach passed.
The cap is approximately 150 mm high; fingertip clearance at approach is about
20 mm. Lift before inward travel is about 50 mm. B retains the 450 mm approach.
All eleven native round-trip planning legs passed before physical execution.

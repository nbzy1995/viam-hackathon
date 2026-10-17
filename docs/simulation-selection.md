# Simulation selection — 2026-10-16

## Decision

**Updated for the user's low-infrastructure preference:** use the existing Viam server and its built-in `arm/simulated` xArm6 component, with native Preview move for planning QA. `qa-sim-arm` has been added and component tests run. Full planner QA is blocked by the existing camera's unlinked frame; the user is resolving that in another session. See [native QA evidence](viam-native-qa.md). No Gazebo infrastructure was installed. The vendor Gazebo route below remains an optional higher-fidelity alternative, not the current implementation plan.

## Earlier higher-fidelity option

For the user's updated priority of realistic physical arm motion, select UFACTORY's official xArm6 Gazebo simulation, with its gripper, using the ROS 2 Jazzy branch on Ubuntu 24.04 and Gazebo Harmonic. This is the best documented fit among the routes inspected, not a claim of measured superior accuracy over every simulator.

The vendor supplies the arm model, simulation controllers and MoveIt/Gazebo launch. Gazebo supplies physics. Start with the vendor example, then add only the table, one block and fixed A/B. Do not substitute a UR5e for the xArm6. Match the hardware revision, gripper and mounting once those details are verified.

The documented simulation launch is:

```sh
ros2 launch xarm_moveit_config xarm6_moveit_gazebo.launch.py add_gripper:=true
```

This command is a setup reference, not evidence that the simulator has been installed or run here. Run only simulation launch files, without robot_ip, hardware drivers or real-machine credentials. Keep the real Viam machine unchanged.

## Evidence and limits

- [UFACTORY official Jazzy documentation](https://github.com/xArm-Developer/xarm_ros2/blob/jazzy/ReadMe.md): xArm6 Gazebo and MoveIt simulation, gripper support, Ubuntu/ROS combinations.
- [Actual xArm6 simulation launch](https://github.com/xArm-Developer/xarm_ros2/blob/jazzy/xarm_moveit_config/launch/xarm6_moveit_gazebo.launch.py): fixes dof=6, robot_type=xarm and gz_type=gz.
- [Actual Gazebo package dependencies](https://github.com/xArm-Developer/xarm_ros2/blob/jazzy/xarm_gazebo/package.xml): gz_ros2_control and ros_gz; prefer these over older Classic instructions still present in parts of the README.
- [Gazebo compatibility documentation](https://gazebosim.org/docs/harmonic/ros_installation/): Jazzy/Harmonic is a recommended pairing on Ubuntu 24.04.
- [Viam fake-arm quickstart](https://docs.viam.com/motion-planning/quickstarts/first-arm/): fake motion is instantaneous and has no dynamics. Useful for Viam API/planning tests, insufficient for physical motion fidelity.
- [Viam preview](https://docs.viam.com/visualization/3d-scene/move-mode/): plans have no timing; preview playback is approximate.
- [Viam Gazebo tutorial](https://docs.viam.com/try/quality-inspection/gazebo-setup/): a conveyor/can inspection example. It demonstrates an integration route but does not supply a ready xArm6/Viam bridge.

MoveIt-generated paths do not establish Viam planner behavior. A later Viam integration needs separate verification; it is not provided by merely launching the vendor simulator. No unverified bridge is included in this decision.

The existing PyBullet tests remain valid for their declared synthetic scene, but do not prove this Gazebo setup, the Viam workflow, or hardware accuracy. Physical fidelity also depends on calibration, inertia, controller settings, payload and friction; it cannot be certified from a simulator name.

## Local readiness

Read-only inspection found approximately 24 GiB free, Docker CLI present, Docker daemon unavailable at its configured socket, and no gz or viam-server executable on PATH. No large images were downloaded, simulator launched, real machine configuration changed, or robot command sent during this selection.

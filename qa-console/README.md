# Persistent SDK console — connection checkpoint

Supporting experiment for the workshop's [Phase 4 Python connection checkpoint](https://docs.viam.com/tutorials/pick-and-place/control-the-robot-from-python/).
One process opens one Viam SDK connection and accepts several commands before
closing. It uses the existing credentials in the repository root's ignored
`.env.viam.json` (`address`, `api_key_id`, `api_key`). Never commit that file.

Run from the repository root:

```sh
uv run python -u qa-console/persistent_sim.py
```

Alternatively, use the script's pinned inline dependency metadata without the
main project's environment:

```sh
uv run --script qa-console/persistent_sim.py
```

Type one command at a time:

| Command | Behavior |
| --- | --- |
| `status` | Read machine status, report RPC time and simulator availability |
| `A` | Move `qa-sim-arm` to synthetic flange position (400, -130, 320) mm |
| `B` | Move `qa-sim-arm` to synthetic flange position (400, 130, 320) mm |
| `quit` | Close the connection and exit |

A and B use a downward tool orientation. They are synthetic test coordinates,
not the physical table markers. The console targets only the name `qa-sim-arm`;
its configured model must remain Viam's built-in simulated arm. It does not
enable components, edit configuration, or operate the real arm or gripper.
Do not enable the shared simulator while another session is using the physical
planning scene. Restart the console after changing simulator availability.

## Evidence and limits

- Live connection succeeded on October 16, 2026 in **3,451.4 ms**.
- The same process accepted `quit`, closed its SDK connection, and exited.
- No motion commands were sent. The shared simulator was disabled.
- A-to-B execution, repeated live commands, and RPC latency are **not yet
  verified**. Connection establishment time is not command latency.
- Offline tests check connection reuse, command routing, and refusing movement
  when the simulator is unavailable. They do not prove simulator motion.

Run offline tests in the existing project environment:

```sh
uv run pytest qa-console/test_persistent_sim.py -q
```

This checkpoint does not claim completion of the workshop's static-transfer or
perception checkpoints. Main-thread work is maintained separately.

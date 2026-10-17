# Conversational table demo

Open http://127.0.0.1:8089/ and select **Start voice conversation**. Wait for each spoken
reply before the next request. The displayed examples are plain suggested
prompts, not action buttons.

1. **“What do you see on my table?”** The arm raises to a high view, turns the
   camera through three angles, captures three images, returns home, and
   describes the images. No object moves during the inspection.
2. **“Bring this water bottle to me.”** The blue-and-white water carton is the
   demo bottle. The robot saves its measured pickup position, delivers it to
   the exposed blue tape marker, verifies placement, and returns home.
3. **“Take the water bottle back.”** The robot picks it up at the delivery
   location, returns it to the saved pickup coordinates, verifies placement,
   and returns home.

Start with the upright carton in the reachable region around A or B. The original A pickup
is reachable; a measured position about 20 mm farther out at [471.7, -510.2]
could not reach the required approach height. The executor refuses that plan
before grasping. “Prepare robot” returns an empty arm home when needed.

The user's location is currently predefined by `config/table-demo.json`,
measured from the single exposed flat blue tape segment at approximately
[475.9, -241.7] mm in world coordinates. It is separate from station B. This
version does not recognize a person or choose a handoff point. Station B is
still used as an intermediate high transit on the established transfer route.

## Integration

The existing interpreter selects `scan_table`, `deliver_bottle`, or
`return_bottle` with no generated movement commands. `TextController` dispatches
`table_demo.py` on its existing robot connection and shared control lock. Voice
and typed requests use exactly the same controller. The same voice transport
speaks the verified result or the image description.

The three-view scan uses flange position [330, -280, 680.6] mm and camera
rotation offsets [0, -15, 15] degrees. This keeps the wrist extended; the older
near-base overview pose triggered the controller's self-collision check when
rotated. All views and the return are previewed before moving. A cancellation
stops the task without initiating a new home move.

Delivery and return reuse `workshop_vision.transfer_carton` at 8 degrees/second,
with acceleration 6 degrees/second² and the existing 45 mm visual placement
tolerance. If an approach posture cannot descend vertically, the routine reuses
the harness's `approach_from_grasp` helper to select a compatible posture and
previews the entire route again before execution. The origin and verified delivery are stored atomically in ignored
`robot_workspace/table-demo-state.json`, bound to the calibration and demo
configuration. A preview never establishes an origin; an interrupted transfer
does not become a verified delivery. Repeating an already completed delivery
or return checks the current position without moving again.

## Fast checks

```sh
uv run --extra voice-ui pytest tests/test_table_demo.py tests/test_workshop_text.py tests/test_vision_cycle.py -q
uv run python evaluate_text.py --suite config/text-table-demo-regressions.json --run-id table-demo-routing
```

The five known language cases cover the three requests, a no-motion request,
and a question about how delivery works. Hardware is not used by these tests.
Live UI results are saved as `artifacts/diagnosis/text-task-*.json`.

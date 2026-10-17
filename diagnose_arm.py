"""Read-only Viam state/model snapshot for investigating the wall contact."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from google.protobuf.json_format import MessageToDict
from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.components.gripper import Gripper


async def main():
    root = Path(__file__).parent
    out = root / 'artifacts/diagnosis'
    out.mkdir(parents=True, exist_ok=True)
    c = json.loads((root / '.env.viam.json').read_text())
    options = RobotClient.Options.with_api_key(api_key=c['api_key'], api_key_id=c['api_key_id'])
    options.dial_options.initial_connection_attempts = 1
    options.dial_options.initial_connection_attempt_timeout = 15
    robot = await RobotClient.at_address(c['address'], options)
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'motion_commands': False}
    async def read(name, awaitable):
        try:
            value = await asyncio.wait_for(awaitable, 15)
            if hasattr(value, 'DESCRIPTOR'):
                value = MessageToDict(value)
            report[name] = value
        except Exception as exc:
            report[name] = {'read_error': str(exc)}
    try:
        arm = Arm.from_robot(robot, 'arm')
        await read('pose', arm.get_end_position(timeout=10))
        await read('joints', arm.get_joint_positions(timeout=10))
        await read('moving', arm.is_moving(timeout=10))
        await read('controller_state', arm.do_command({'get_state': True}, timeout=10))
        await read('controller_error', arm.do_command({'get_error': True}, timeout=10))
        frames = await asyncio.wait_for(robot.get_frame_system_config(), 15)
        report['frames'] = [MessageToDict(f.frame) for f in frames]
        for f in frames:
            if f.frame.reference_frame in ('arm', 'qa-sim-arm'):
                (out / f'{f.frame.reference_frame}-frame-kinematics.json').write_text(json.dumps(MessageToDict(f.kinematics)))
        k = await arm.get_kinematics(timeout=15)
        (out / 'arm-kinematics.model').write_bytes(k[1])
        report['arm_kinematics'] = {'format': int(k[0]), 'bytes': len(k[1])}
        if len(k) > 2:
            report['mesh_files'] = list(k[2])
        report['obstacle_geometries'] = {}
        for name in ['table', 'wall-front', 'wall-side', 'ceiling', 'gripper']:
            try:
                geometries = await Gripper.from_robot(robot, name).get_geometries(timeout=10)
                report['obstacle_geometries'][name] = [MessageToDict(g) for g in geometries]
            except Exception as exc:
                report['obstacle_geometries'][name] = {'read_error': str(exc)}
        await read('machine_status', robot.get_machine_status())
    finally:
        await robot.close()
        (out / 'live-state.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: v for k, v in report.items() if k not in ['machine_status', 'mesh_files']}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())

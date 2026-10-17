"""Read-only Phase 5 checkpoint: native detections and 3D segments from home."""
import asyncio,json
from pathlib import Path
from google.protobuf.json_format import MessageToDict
from viam.robot.client import RobotClient
from viam.components.arm import Arm
from viam.services.vision import VisionClient
from viam.proto.common import PoseInFrame
from workshop_static import check_arm
async def main():
 c=json.load(open('.env.viam.json'));o=RobotClient.Options.with_api_key(api_key=c['api_key'],api_key_id=c['api_key_id']);o.dial_options.force_relay=True;o.dial_options.initial_connection_attempts=1;o.dial_options.initial_connection_attempt_timeout=15
 r=await asyncio.wait_for(RobotClient.at_address(c['address'],o),25)
 out={'motion_commanded':False}
 try:
  a=Arm.from_robot(r,'arm');await check_arm(a);q=list((await a.get_joint_positions(timeout=5)).values)
  home=json.load(open('artifacts/roundtrip-checked-setup.json'))['home_joints'];assert max(abs(x-y) for x,y in zip(q,home))<.1,'Observe from home'
  names=[n.name for n in r.resource_names];out['vision_resources']=[n for n in ['carton-detector','vision-segment'] if n in names]
  if len(out['vision_resources'])!=2:raise RuntimeError('Vision resources are not ready yet')
  detector=VisionClient.from_robot(r,'carton-detector');vision=VisionClient.from_robot(r,'vision-segment')
  out['detections']=[MessageToDict(x) for x in await detector.get_detections_from_camera('cam',timeout=15)]
  out['objects']=[]
  for obj in await vision.get_object_point_clouds('cam',timeout=15):
   geos=[]
   for g in obj.geometries.geometries:
    world=await r.transform_pose(PoseInFrame(reference_frame='cam',pose=g.center),'world')
    geos.append({'geometry':MessageToDict(g),'world_center':MessageToDict(world.pose)})
   out['objects'].append({'pcd_bytes':len(obj.point_cloud),'geometries':geos})
 except Exception as e:out['error']=str(e)
 finally:
  Path('artifacts/diagnosis/phase5-perception.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2));await asyncio.wait_for(r.close(),5)
if __name__=='__main__':asyncio.run(main())

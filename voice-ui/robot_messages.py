"""User-facing task results derived only from controller evidence."""

def task_answer(result):
    outcome = result.get('outcome')
    if outcome == 'table_scanned' and result.get('success'):
        return result['task']['message']
    if outcome == 'bottle_delivered' and result.get('success'):
        return 'Your water bottle is at your blue tape marker. I saved its original position and returned home.'
    if outcome == 'bottle_returned' and result.get('success'):
        return 'The water bottle is back where I picked it up. I verified its position and returned home.'
    if outcome == 'roundtrip_completed' and result.get('success'):
        return 'Vision round trip passed. The carton moved A to B to A. Fresh camera observations verified each placement, and the arm returned home.'
    if outcome == 'robot_checked':
        return 'Robot connected. The arm is stationary and the setup matches calibration. ' + ('The gripper is holding an object.' if result['holding'] else 'The gripper is empty.') + (' Ready for the motion check.' if result['at_home'] and not result['holding'] else ' Prepare the robot before the motion check.')
    if outcome == 'motion_checked' and result.get('success'):
        return f"Motion check passed. The arm turned 5 degrees and returned to the ready pose. Both endpoints were verified within {result['max_joint_error_degrees']:.3f} degrees."
    if outcome == 'ready':
        return 'The robot is ready at the checked observation pose. You can now ask it to move an object.'
    if outcome == 'completed' and result.get('success'):
        verification = result.get('verification', {})
        if 'error_mm' in verification:
            return f"Task completed. The camera verified the placement within {verification['error_mm']:.1f} mm of the target."
        return 'Task completed and its placement was verified by the camera.'
    error = result.get('error', '')
    if error:
        if result.get('execution_attempted'):
            stop = ' The robot acknowledged a stop.' if result.get('stop_requested') else ' Robot stop is not confirmed.'
            return 'The task did not complete or its placement could not be verified.' + stop
        if 'checked home pose' in error:
            return 'The robot needs preparation. Say “Prepare robot”, then try your request again.'
        if 'Another robot operation' in error:
            return 'Another robot operation is active. Wait for it to finish before trying again.'
        if 'setup changed' in error:
            return 'The robot setup changed. Its calibration needs checking before movement.'
        if 'native planning' in error or any(word in error.lower() for word in ('preview', 'clearance', 'unreachable')):
            return 'That route is blocked or unreachable. No object transfer was started. Try a different direction or destination.'
        if 'position during planning' in error or 'scene changed' in error:
            return 'The scene changed while planning. No object transfer was started. Please try again with the scene still.'
        return 'The robot could not complete the checks needed for this task. No object transfer was started.'
    return result.get('task', {}).get('message', 'The task did not complete.')

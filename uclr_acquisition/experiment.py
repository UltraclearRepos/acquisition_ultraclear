import os
import time
from uclr_acquisition.config import config
from uclr_acquisition.dobot import connect_robot, enable_robot, disable_robot, move_to_position, DobotLogger
from .record import start_recording, stop_recording, kill_recording
from .utils import build_filename

dashboard = None
move = None
dobot_logger = None
    
def safe_run_automation(socketio_instance, **kwargs):
    """
    Wrapper function to run the automation, handle any exception and proceed actions that is needed when automation stopped working
    """
    global dashboard, move, dobot_logger
    try:
        run_automation(**kwargs, socketio_instance=socketio_instance)
    except Exception as e:
        print(f'AUTOMATION STOPPED WITH ERROR: {e}')
        socketio_instance.emit("automation-status", {
            "status": "idle",
        })
        if dobot_logger:
            dobot_logger.stop()
            dobot_logger = None
        kill_recording(socketio_instance)
        if dashboard:
            disable_robot(dashboard)
            dashboard.close()
        if move:
            move.close()
        dashboard = None
        move = None


def run_automation(
        points, 
        speed, 
        description, 
        num_iterations, 
        num_repetitions,
        sleep_time, 
        stop_event, 
        socketio_instance):
    """
    Main automation functions:
      - Connects to the Dobot Mg400,
      - Iterates through the given number of loops,
      - Moves the robot through sequence of points and records audio+video.
    """
    global dashboard, move, dobot_logger
    print("Executing 'run_automation'")

    socketio_instance.emit("automation-status", {
        "status": "running",
    })

    dashboard, move = connect_robot()
    enable_robot(dashboard)
    time.sleep(2)

    if not points:
        print("No points provided. Exiting.")
        return

    first_point = (points[0]['x'], points[0]['y'], points[0]['z'], points[0]['r'])

    for i in range(num_iterations):

        if stop_event.is_set():
            print("Stop event triggered. Exiting loop.")
            break

        socketio_instance.emit("iteration", {
            "iteration": i+1
        })

        # Move to the first point before recording
        move_to_position(dashboard, move, first_point, speed_l=speed)
        print(f'Moving to initial position: {first_point}')
        time.sleep(0.3)

        output_filename_prefix = build_filename(description, f'Speed-{speed}')
        
        is_started, msg = start_recording(output_filename_prefix, socketio_instance)

        if not is_started:
            raise RuntimeError(f"Recording failed: {msg}")

        dobot_filepath = os.path.join("dobot", f"{output_filename_prefix}.csv")
        dobot_logger = DobotLogger(dashboard, dobot_filepath)
        dobot_logger.start()

        time.sleep(0.5)
        print(f"Recording {i+1}/{num_iterations} started.")

        for _ in range(num_repetitions):
            if stop_event.is_set():
                break

            for idx in range(1, len(points)):
                if stop_event.is_set():
                    break        
                p = points[idx]
                target_point = (p['x'], p['y'], p['z'], p['r'])
                move_to_position(dashboard, move, target_point, speed_l=speed)
                print(f'Moving to point {idx + 1}: {target_point}')
                time.sleep(sleep_time)

            # Go back to the first point to close the loop
            if len(points) > 1 and not stop_event.is_set():
                move_to_position(dashboard, move, first_point, speed_l=speed)
                print(f'Moving back to initial position: {first_point}')
                time.sleep(sleep_time)
        
        time.sleep(0.5)

        stop_recording(socketio_instance)
        dobot_logger.stop_and_save()
        dobot_logger = None

        time.sleep(1)

        print(f"Iteration {i+1} completed.")

    disable_robot(dashboard)
    dashboard.close()
    move.close()
    dashboard = None
    move = None
    dobot_logger = None
    socketio_instance.emit("automation-status", {
        "status": "idle",
    })
    print(f"Tests completed.")

if __name__ == "__main__":
    run_automation(
        username="test_user",
        material=config["materials"][0],
        speed=config["speeds"][1],
        motion_type=None,
        p1=None,
        p2=None,
        p3=None,
        num_iterations=None,
        num_repetitions=None
    ) 

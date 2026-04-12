import time
from uclr_acquisition.config import config
from uclr_acquisition.comm import on_rec_start, on_rec_stop, kill_rasp_process
from uclr_acquisition.dobot import connect_robot, enable_robot, disable_robot, move_to_position
from .record import start_recording, stop_recording
from .utils import build_filename

dashboard = None
    
def safe_run_automation(socketio_instance, **kwargs):
    """
    Wrapper function to run the automation, handle any exception and proceed actions that is needed when automation stopped working
    """
    global dashboard
    try:
        run_automation(**kwargs, socketio_instance=socketio_instance)
    except Exception as e:
        print(f'AUTOMATION STOPPED WITH ERROR: {e}')
        kill_rasp_process()
        socketio_instance.emit("automation-status", {
            "status": "idle",
        })
        socketio_instance.emit("record", {
            "action": "stop",
            "shouldUpload": False
        })
        if dashboard:
            disable_robot(dashboard)
        dashboard = None


def run_automation(
        points, 
        speed, 
        description, 
        num_iterations, 
        sleep_time, 
        stop_event, 
        socketio_instance):
    """
    Main automation functions:
      - Connects to the Dobot Mg400,
      - Iterates through the given number of loops,
      - Moves the robot through sequence of points and records audio+video.
    """
    global dashboard
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
        
        is_started = start_recording(output_filename_prefix, socketio_instance)

        if not is_started:
            continue

        time.sleep(0.5)
        print(f"Recording {i+1}/{num_iterations} started.")

        # Follow the rest of the points (if there's more than 1 point)
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
            time.sleep(0.5)

        stop_recording(socketio_instance)

        time.sleep(1)

        print(f"Iteration {i+1} completed.")

    disable_robot(dashboard)
    dashboard = None
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
        num_iterations=None
    ) 
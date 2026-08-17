import os
import time
import math
from uclr_acquisition.config import config
from uclr_acquisition.dobot import (
    connect_robot,
    enable_robot,
    disable_robot,
    move_to_position,
    move_to_joint_position,
    move_along_arc,
    DobotLogger,
)
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


def safe_run_arc_automation(socketio_instance, **kwargs):
    """Run the 180-degree arc mode with the standard error cleanup."""
    global dashboard, move, dobot_logger
    try:
        run_arc_automation(**kwargs, socketio_instance=socketio_instance)
    except Exception as e:
        print(f'ARC AUTOMATION STOPPED WITH ERROR: {e}')
        socketio_instance.emit("automation-status", {"status": "idle"})
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


def calculate_arc_points(center_x, center_y, z_fixed, radius):
    """Calculate start, mid and end poses for the fixed -90..+90 arc."""
    points = []
    for angle_degrees in (-90.0, 0.0, 90.0):
        angle = math.radians(angle_degrees)
        x = center_x - radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        tool_r = -angle_degrees
        points.append((x, y, z_fixed, tool_r))
    return tuple(points)


def run_arc_automation(
        center_x,
        center_y,
        z_fixed,
        radius,
        speed,
        description,
        num_iterations,
        num_repetitions,
        initial_sleep_time,
        sleep_time,
        stop_event,
        socketio_instance):
    """Record repeated forward and return movements over a 180-degree arc."""
    global dashboard, move, dobot_logger
    print("Executing 'run_arc_automation'")

    if radius <= 0:
        raise ValueError("Arc radius must be greater than zero")

    start_point, mid_point, end_point = calculate_arc_points(
        center_x, center_y, z_fixed, radius
    )
    print(
        f"Arc points: start={start_point}, mid={mid_point}, "
        f"end={end_point}"
    )

    socketio_instance.emit("automation-status", {"status": "running"})
    dashboard, move = connect_robot()
    enable_robot(dashboard)
    time.sleep(2)

    for i in range(num_iterations):
        if stop_event.is_set():
            print("Stop event triggered. Exiting arc loop.")
            break

        socketio_instance.emit("iteration", {"iteration": i + 1})
        move_to_joint_position(dashboard, move, start_point, speed_j=speed)
        print(f"Moving to arc start: {start_point}")
        time.sleep(0.3)

        output_filename_prefix = build_filename(
            description, f'Arc180-Speed-{speed}'
        )
        dobot_filepath = os.path.join(
            "dobot", f"{output_filename_prefix}.csv"
        )
        dobot_logger = DobotLogger(dashboard, dobot_filepath)
        dobot_logger.start()

        is_started, msg = start_recording(
            output_filename_prefix, socketio_instance
        )
        if not is_started:
            raise RuntimeError(f"Recording failed: {msg}")

        if initial_sleep_time > 0:
            time.sleep(initial_sleep_time)

        for _ in range(num_repetitions):
            if stop_event.is_set():
                break

            move_along_arc(
                dashboard, move, mid_point, end_point, speed_l=speed
            )
            print("Forward arc completed.")
            time.sleep(sleep_time)

            if stop_event.is_set():
                break

            move_along_arc(
                dashboard, move, mid_point, start_point, speed_l=speed
            )
            print("Return arc completed.")
            time.sleep(sleep_time)

        time.sleep(0.5)
        is_stopped, stop_message = stop_recording(socketio_instance)
        dobot_logger.stop_and_save()
        dobot_logger = None
        if not is_stopped:
            raise RuntimeError(f"Recording stop failed: {stop_message}")

        time.sleep(1)
        print(f"Arc iteration {i + 1} completed.")

    disable_robot(dashboard)
    dashboard.close()
    move.close()
    dashboard = None
    move = None
    dobot_logger = None
    socketio_instance.emit("automation-status", {"status": "idle"})
    print("Arc tests completed.")


def run_automation(
        points, 
        speed, 
        description, 
        num_iterations, 
        num_repetitions,
        initial_sleep_time,
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

        dobot_filepath = os.path.join("dobot", f"{output_filename_prefix}.csv")
        dobot_logger = DobotLogger(dashboard, dobot_filepath)
        dobot_logger.start()

        is_started, msg = start_recording(output_filename_prefix, socketio_instance)

        if not is_started:
            raise RuntimeError(f"Recording failed: {msg}")

        print(f"Recording {i+1}/{num_iterations} started.")

        if initial_sleep_time > 0:
            print(
                f"Waiting {initial_sleep_time}s before moving "
                "to the second point."
            )
            time.sleep(initial_sleep_time)

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

        is_stopped, stop_message = stop_recording(socketio_instance)
        dobot_logger.stop_and_save()
        dobot_logger = None
        if not is_stopped:
            raise RuntimeError(f"Recording stop failed: {stop_message}")

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
        speed=50,
        motion_type=None,
        p1=None,
        p2=None,
        p3=None,
        num_iterations=None,
        num_repetitions=None
    ) 

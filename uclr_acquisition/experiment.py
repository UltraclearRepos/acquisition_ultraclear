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
from .grid_config import (
    grid_point_name,
    grid_safe_position,
    grid_point_position,
    count_grid_points,
)

dashboard = None
move = None
dobot_logger = None


def handle_automation_error(socketio_instance, error, mode_name):
    """Stop logging and recording and release the robot after an automation error."""
    global dashboard, move, dobot_logger
    print(f'{mode_name} STOPPED WITH ERROR: {error}')
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


def safe_run_points_automation(socketio_instance, **kwargs):
    """
    Wrapper function to run the coordinate path automation, handle any exception and proceed actions that is needed when automation stopped working
    """
    try:
        run_points_automation(**kwargs, socketio_instance=socketio_instance)
    except Exception as e:
        handle_automation_error(socketio_instance, e, "POINTS AUTOMATION")


def safe_run_arc_automation(socketio_instance, **kwargs):
    """Run the 180-degree arc mode with the standard error cleanup."""
    try:
        run_arc_automation(**kwargs, socketio_instance=socketio_instance)
    except Exception as e:
        handle_automation_error(socketio_instance, e, "ARC AUTOMATION")


def safe_run_updown_automation(socketio_instance, **kwargs):
    """Run the up/down mode with the standard error cleanup."""
    try:
        run_updown_automation(**kwargs, socketio_instance=socketio_instance)
    except Exception as e:
        handle_automation_error(socketio_instance, e, "UP/DOWN AUTOMATION")


def safe_run_grid_automation(socketio_instance, **kwargs):
    """Run the grid mode with the standard error cleanup."""
    try:
        run_grid_automation(**kwargs, socketio_instance=socketio_instance)
    except Exception as e:
        handle_automation_error(socketio_instance, e, "GRID AUTOMATION")


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

def run_points_automation(
        points, 
        speed, 
        description, 
        material,
        needle_type,
        microphone_type,
        num_iterations, 
        num_repetitions,
        initial_sleep_time,
        sleep_time, 
        stop_event, 
        socketio_instance):
    """
    Coordinate path automation:
      - Connects to the Dobot Mg400,
      - Iterates through the given number of loops,
      - Moves the robot through sequence of points and records audio+video.
    """
    global dashboard, move, dobot_logger
    print("Executing 'run_points_automation'")

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

        output_filename_prefix = build_filename(
            description, material, f'Speed-{speed}', needle_type, microphone_type
        )

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

def run_arc_automation(
        center_x,
        center_y,
        z_fixed,
        radius,
        speed,
        description,
        material,
        needle_type,
        microphone_type,
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
            description, material, f'Arc180-Speed-{speed}',
            needle_type, microphone_type
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


def run_updown_automation(
        init_x,
        finish_x,
        y,
        up_z,
        down_z,
        r,
        motion_type,
        interval,
        speed,
        description,
        material,
        needle_type,
        microphone_type,
        num_iterations,
        initial_sleep_time,
        sleep_time,
        stop_event,
        socketio_instance):
    """
    Record one up/down movement per iteration.

    With interval smaller than (up_z - down_z), the robot goes down and up
    in interval steps and waits sleep_time at every step. In the
    "up_down_forward" motion type, X moves by (finish_x - init_x) / num_iterations
    after every iteration.
    """
    global dashboard, move, dobot_logger
    print("Executing 'run_updown_automation'")

    if interval <= 0:
        raise ValueError("Interval must be greater than zero")

    socketio_instance.emit("automation-status", {"status": "running"})
    dashboard, move = connect_robot()
    enable_robot(dashboard)
    time.sleep(2)

    if motion_type == "up_down_forward":
        gap = (finish_x - init_x) / num_iterations
        print(f"Gap between X positions: {gap}")
    else:
        gap = 0

    p1 = (init_x, y, up_z, r)
    p2 = (init_x, y, down_z, r)

    for i in range(num_iterations):
        if stop_event.is_set():
            print("Stop event triggered. Exiting up/down loop.")
            break

        socketio_instance.emit("iteration", {"iteration": i + 1})
        move_to_position(dashboard, move, p1, speed_l=speed)
        print(f"Moving to initial position: {p1}")
        time.sleep(0.3)

        output_filename_prefix = build_filename(
            description, material, f'UpDown-Speed-{speed}',
            needle_type, microphone_type
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

        print(f"Recording {i + 1}/{num_iterations} started.")

        if initial_sleep_time > 0:
            time.sleep(initial_sleep_time)

        curr_z = p1[2] - interval
        while curr_z >= down_z:
            p2 = (p2[0], p2[1], curr_z, p2[3])
            move_to_position(dashboard, move, p2, speed_l=speed)
            print(f"Moving down to: {p2}")
            time.sleep(sleep_time)
            curr_z -= interval

        curr_z += 2 * interval
        while curr_z <= up_z and interval != up_z - down_z:
            p2 = (p2[0], p2[1], curr_z, p2[3])
            move_to_position(dashboard, move, p2, speed_l=speed)
            print(f"Moving up to: {p2}")
            curr_z += interval
            if curr_z <= up_z:
                time.sleep(sleep_time)

        move_to_position(dashboard, move, p1, speed_l=speed)
        print(f"Moving back to initial position: {p1}")
        time.sleep(0.5)

        p1 = (p1[0] + gap, p1[1], up_z, p1[3])
        p2 = (p2[0] + gap, p2[1], down_z, p2[3])

        is_stopped, stop_message = stop_recording(socketio_instance)
        dobot_logger.stop_and_save()
        dobot_logger = None
        if not is_stopped:
            raise RuntimeError(f"Recording stop failed: {stop_message}")

        time.sleep(1)
        print(f"Up/down iteration {i + 1} completed.")

    disable_robot(dashboard)
    dashboard.close()
    move.close()
    dashboard = None
    move = None
    dobot_logger = None
    socketio_instance.emit("automation-status", {"status": "idle"})
    print("Up/down tests completed.")


def run_grid_automation(
        grid_config,
        speed,
        description,
        material,
        needle_type,
        microphone_type,
        sleep_time,
        stop_event,
        socketio_instance):
    """
    Record every grid point from the grid config file.

    The robot moves in XY at the safe initial Z height, goes down through
    the Z values of each point and is disabled while recording sleep_time
    seconds at each measurement point.
    """
    global dashboard, move, dobot_logger
    print("Executing 'run_grid_automation'")

    total_points = count_grid_points(grid_config)
    completed = 0

    socketio_instance.emit("automation-status", {"status": "running"})
    dashboard, move = connect_robot()
    enable_robot(dashboard)
    time.sleep(2)

    should_stop = False
    for column_config in grid_config["y_columns"]:
        y = column_config["y"]
        column = column_config["column"]

        for row_config in grid_config["x_rows"]:
            if stop_event.is_set():
                should_stop = True
                break

            x = row_config["x"]
            row = row_config["row"]
            safe_position = grid_safe_position(x, y, grid_config)

            print(f"Row {row}, column {column}: X={x}, Y={y}")
            move_to_position(dashboard, move, safe_position, speed_l=speed)

            for z in column_config["z_values"]:
                if stop_event.is_set():
                    should_stop = True
                    break

                point_name = grid_point_name(
                    column, row, z, grid_config["z_distance_map"]
                )
                socketio_instance.emit("iteration", {
                    "iteration": completed + 1,
                    "total": total_points,
                    "label": point_name,
                })

                point_position = grid_point_position(x, y, z, grid_config)
                print(f"Moving to grid point {point_name}: {point_position}")
                move_to_position(dashboard, move, point_position, speed_l=speed)

                disable_robot(dashboard)

                output_filename_prefix = build_filename(
                    point_name, description, material, f'Grid-Speed-{speed}',
                    needle_type, microphone_type
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

                print(f"Recording started for {point_name}.")
                time.sleep(sleep_time)

                is_stopped, stop_message = stop_recording(socketio_instance)
                dobot_logger.stop_and_save()
                dobot_logger = None
                if not is_stopped:
                    raise RuntimeError(f"Recording stop failed: {stop_message}")

                print(f"Recording stopped for {point_name}.")
                completed += 1
                enable_robot(dashboard)

                if stop_event.is_set():
                    should_stop = True
                    break

            move_to_position(dashboard, move, safe_position, speed_l=speed)

            if should_stop:
                break

        if should_stop:
            break

    print(f"Grid automation completed: {completed}/{total_points} point(s)")

    disable_robot(dashboard)
    dashboard.close()
    move.close()
    dashboard = None
    move = None
    dobot_logger = None
    socketio_instance.emit("automation-status", {"status": "idle"})

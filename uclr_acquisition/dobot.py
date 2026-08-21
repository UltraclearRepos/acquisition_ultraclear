import time
import os
import threading
from uclr_acquisition.dobot_api import DobotApiDashboard, DobotApiMove

# ---------------------------------------------
# Robot IP and Port settings
# ---------------------------------------------
ROBOT_IP = "192.168.1.6"
DASHBOARD_PORT = 29999
MOVE_PORT = 30003
FEED_PORT = 30004


def parse_pose(response):
    """
    Parses the output of Dobot's GetPose() and returns a list [X, Y, Z, R, ...].
    Example response: 'GetPose({300.0, 0.0, 100.0, 0.0, ...})'
    """
    try:
        pose_data = response.split("{")[1].split("}")[0]
        pose_values = [float(val) for val in pose_data.split(",")]
        return pose_values
    except Exception as e:
        print(f"Error (pose parse): {e}")
        return None


def connect_robot():
    """Connect to the Dobot MG400 and return (dashboard, move) API instances."""
    try:
        print("Connecting to the robot...")
        dashboard = DobotApiDashboard(ROBOT_IP, DASHBOARD_PORT)
        move = DobotApiMove(ROBOT_IP, MOVE_PORT)
        print("Connection successful!")
        return dashboard, move
    except Exception as e:
        print("Connection failed :(")
        raise e


def enable_robot(dashboard, load=None, center_x=None, center_y=None, center_z=None):
    """
    Enable the robot. Optionally pass load parameters.
    """
    try:
        print("Enabling the robot...")
        if load is not None:
            dashboard.EnableRobot(load, center_x, center_y, center_z)
        else:
            dashboard.EnableRobot()
        dashboard.SpeedFactor(100)
        print("Robot enabled! (SpeedFactor reset to 100%)")
    except Exception as e:
        print("Error during robot enabling :(")
        raise e


def disable_robot(dashboard):
    """Disable the robot."""
    dashboard.DisableRobot()
    print("Robot disabled.")


def wait_for_position(dashboard, position, tolerance=1.0):
    """Wait until the robot reaches an (x, y, z, r) target."""
    x, y, z, r = position
    while True:
        time.sleep(0.05)
        response = dashboard.GetPose()
        pose_vals = parse_pose(response)
        if pose_vals:
            curr_x, curr_y, curr_z, curr_r = pose_vals[:4]
            if (abs(curr_x - x) < tolerance and
                    abs(curr_y - y) < tolerance and
                    abs(curr_z - z) < tolerance and
                    abs(curr_r - r) < tolerance):
                return


def move_to_position(dashboard, move, position, speed_l, acc_l=20, tolerance=1.0):
    """
    Move to the given (x, y, z, r) position using MovL and wait until arrival.

    Speed is controlled solely via the inline SpeedL parameter passed to MovL.
    No global SpeedFactor or Dashboard SpeedL/AccL calls are made here — keeping
    a single, explicit source of truth for movement speed.

    Parameters:
        dashboard: DobotApiDashboard instance (used only for GetPose polling)
        move: DobotApiMove instance
        position: tuple (x, y, z, r)
        speed_l: Cartesian speed ratio for MovL (1-100)
        acc_l: Cartesian acceleration ratio for MovL (1-100)
        tolerance: Position tolerance in mm for determining arrival

    Returns:
        Elapsed time in seconds (float).
    """
    x, y, z, r = position
    print(f"\n[Action] --> {position}, SpeedL={speed_l}, AccL={acc_l}")

    dashboard.AccL(acc_l)
    dashboard.SpeedL(speed_l)

    start_time = time.time()

    move.MovL(x, y, z, r, "User=0", "Tool=0")

    wait_for_position(dashboard, position, tolerance=tolerance)

    end_time = time.time()
    duration = end_time - start_time
    print(f"Action completed, time: {duration:.2f} seconds")
    return duration


def move_to_joint_position(dashboard, move, position, speed_j, acc_j=20,
                           tolerance=1.0):
    """Move to an (x, y, z, r) position with MovJ and wait for arrival."""
    x, y, z, r = position
    dashboard.AccJ(acc_j)
    dashboard.SpeedJ(speed_j)
    move.MovJ(x, y, z, r, "User=0", "Tool=0")
    wait_for_position(dashboard, position, tolerance=tolerance)


def move_along_arc(dashboard, move, mid_point, end_point, speed_l,
                   acc_l=20, tolerance=1.0):
    """Execute Arc(mid, end) from the current pose and wait for arrival."""
    dashboard.AccL(acc_l)
    dashboard.SpeedL(speed_l)
    move.Arc(*mid_point, *end_point, "User=0", "Tool=0")
    wait_for_position(dashboard, end_point, tolerance=tolerance)


class DobotLogger(threading.Thread):
    def __init__(self, dashboard, filepath, sample_period=0.05):
        super().__init__()
        self.dashboard = dashboard
        self.filepath = filepath
        self.sample_period = sample_period
        self.running = True
        self.samples = []
        self.daemon = True

    def _read_pose_sample(self):
        response = self.dashboard.GetPose()
        pose_vals = parse_pose(response)
        if not pose_vals:
            return None

        x, y, z, r = pose_vals[:4]
        timestamp = time.time()
        return (timestamp, x, y, z, r)

    def run(self):
        while self.running:
            loop_start = time.perf_counter()
            try:
                sample = self._read_pose_sample()
                if sample:
                    self.samples.append(sample)
            except Exception as e:
                print(f"DobotLogger error: {e}")

            elapsed = time.perf_counter() - loop_start
            time.sleep(max(0, self.sample_period - elapsed))

    def save(self):
        directory = os.path.dirname(self.filepath)
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(self.filepath, 'w') as f:
            f.write("timestamp,x,y,z,r\n")
            for timestamp, x, y, z, r in self.samples:
                f.write(f"{timestamp:.4f},{x:.4f},{y:.4f},{z:.4f},{r:.4f}\n")

    def stop(self):
        self.running = False
        if self.is_alive():
            self.join()

    def stop_and_save(self):
        self.stop()
        self.save()

import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify, send_from_directory, Response
import cv2
from uclr_acquisition.config import config
from uclr_acquisition.experiment import safe_run_automation
from .record import start_recording, stop_recording, delete_last_recording
from .utils import build_filename, get_local_ip_address
import threading
import webbrowser
import argparse
import os
from pathlib import Path
from flask_socketio import SocketIO
from uclr_acquisition import sensors, trackers
from uclr_acquisition.config import config
from uclr_acquisition.sensors.usg import USGScanner
from uclr_acquisition.sensors.mems import MEMSMicrophone
from uclr_acquisition.trackers.imu import IMUTracker
from uclr_acquisition.trackers.psmove import PSMoveTracker
from uclr_acquisition.runtime_config import runtime_config


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="")
app.config["JSON_AS_ASCII"] = False

socketio = SocketIO(app, cors_allowed_origins="*")

automation_thread = None
stop_event = threading.Event()


@app.route("/upload", methods=['POST'])
def upload_video():
    print(f'Received upload request')
    file = request.files['file']
    filename = file.filename
    video_output_dir = os.path.join(os.getcwd(), "videos")
    os.makedirs(video_output_dir, exist_ok=True)

    file_path = os.path.join(video_output_dir, filename)
    file.save(file_path)
    print(f"File saved to {file_path}")

    start_timestamp = request.form.get("start_timestamp")
    if start_timestamp:
        video_ts_dir = os.path.join(os.getcwd(), "video_timestamps")
        os.makedirs(video_ts_dir, exist_ok=True)
        base = os.path.splitext(filename)[0]
        for suffix in ("_cam1", "_cam2"):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        video_ts_path = os.path.join(video_ts_dir, f"{base}.csv")
        if not os.path.exists(video_ts_path):
            with open(video_ts_path, 'w') as f:
                f.write("source,start_timestamp\n")
                f.write(f"cam1_cam2,{start_timestamp}\n")
            print(f"Camera start timestamp saved to {video_ts_path}")

    return jsonify({"status": "ok", "filename": filename})


@app.route("/", methods=['GET'])
def frontpage():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route('/usg_feed')
def usg_feed():
    def generate():
        while True:
            if sensors.usg_scanner is None or not sensors.usg_scanner.is_initialized:
                eventlet.sleep(1)
                continue
            
            with sensors.usg_scanner.lock:
                frame = sensors.usg_scanner.latest_frame

            if frame is not None:
                ret, buffer = cv2.imencode('.jpg', frame)
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            
            eventlet.sleep(0.03)
            
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/usg-toggle', methods=['POST'])
def usg_toggle():

    print("Received usg-toggle/POST request")

    if sensors.usg_scanner is None:
        return jsonify({"status": "error", "message": "USG not initialized"})
    
    data = request.json
    action = data.get("action")
    print(f'With action: {action}')
    
    if action == "turn_on":
        sensors.usg_scanner.turn_on()
    elif action == "turn_off":
        success, msg = sensors.usg_scanner.turn_off()
        if not success:
            return jsonify({"status": "error", "message": msg})
            
    return jsonify({"status": "ok"})

@app.route('/device-usg-toggle', methods=['POST'])
def device_usg_toggle():
    print("Received device-usg-toggle/POST request")
    data = request.json
    enable = data.get("enable")
    
    if enable:
        if not sensors.usg_scanner:
            try:
                sensors.usg_scanner = USGScanner(config["usg_dll_path"])
                sensors.usg_scanner.connect()
                sensors.usg_scanner.start()
                runtime_config.set_value('usg_enabled', True)
                return jsonify({"status": "ok", "state": "on"})
            except Exception as e:
                print(f"Failed to start USG: {e}")
                if sensors.usg_scanner:
                    sensors.usg_scanner.stop()
                    sensors.usg_scanner = None
                return jsonify({"status": "error", "message": str(e)}), 500
        else:
            runtime_config.set_value('usg_enabled', True)
            return jsonify({"status": "ok", "state": "on"})
    else:
        if sensors.usg_scanner:
            if sensors.usg_scanner.is_initialized:
                sensors.usg_scanner.stop()
            sensors.usg_scanner = None
        runtime_config.set_value('usg_enabled', False)
        return jsonify({"status": "ok", "state": "off"})

@app.route('/device-tracker-toggle', methods=['POST'])
def device_tracker_toggle():
    print("Received device-tracker-toggle/POST request")
    data = request.json
    tracker_type = data.get("tracker") # "imu" or "psmove"
    enable = data.get("enable")
    
    if enable:
        if tracker_type not in trackers.active_trackers:
            try:
                if tracker_type == "imu":
                    new_tracker = IMUTracker(config["imu_port"])
                elif tracker_type == "psmove":
                    new_tracker = PSMoveTracker(config["psmove_dll_path"])
                else:
                    return jsonify({"status": "error", "message": f"Unknown tracker type: {tracker_type}"}), 400
                    
                new_tracker.connect()
                new_tracker.start()
                trackers.active_trackers[tracker_type] = new_tracker
                
                if tracker_type not in runtime_config['active_trackers']:
                    runtime_config['active_trackers'].append(tracker_type)
                    
                return jsonify({"status": "ok", "state": "on"})
            except Exception as e:
                print(f"Failed to start {tracker_type} Tracker: {e}")
                return jsonify({"status": "error", "message": str(e)}), 500
        else:
            if tracker_type not in runtime_config['active_trackers']:
                runtime_config['active_trackers'].append(tracker_type)
            return jsonify({"status": "ok", "state": "on"})
    else:
        if tracker_type in trackers.active_trackers:
            tracker_inst = trackers.active_trackers.pop(tracker_type)
            if getattr(tracker_inst, 'is_connected', False) or getattr(tracker_inst, 'running', False):
                tracker_inst.stop()
                
        if tracker_type in runtime_config['active_trackers']:
            runtime_config['active_trackers'].remove(tracker_type)
            
        return jsonify({"status": "ok", "state": "off"})

@app.route('/device-mems-toggle', methods=['POST'])
def device_mems_toggle():
    print("Received device-mems-toggle/POST request")
    enable = bool((request.get_json(silent=True) or {}).get("enable"))

    if enable:
        if (sensors.mems_microphone is None or not sensors.mems_microphone.is_connected):
            try:
                if sensors.mems_microphone is not None:
                    sensors.mems_microphone.disconnect()
                rpi_config = config["raspberry_pi"]
                sensors.mems_microphone = MEMSMicrophone(
                    hostname=rpi_config["host"],
                    port=rpi_config["port"],
                    username=rpi_config["username"],
                    password=rpi_config["password"],
                    remote_dir=config["remote_dir"],
                    local_dir=config["local_dir"],
                )
                sensors.mems_microphone.connect()
            except Exception as exc:
                print(f"Failed to connect Raspberry Pi MEMS microphone: {exc}")
                if sensors.mems_microphone is not None:
                    try:
                        sensors.mems_microphone.disconnect()
                    except Exception:
                        pass
                sensors.mems_microphone = None
                runtime_config.set_value('mems_enabled', False)
                return jsonify({
                    "status": "error",
                    "message": str(exc),
                }), 500
        runtime_config.set_value('mems_enabled', True)
        return jsonify({"status": "ok", "state": "on"})

    if sensors.mems_microphone is not None:
        if sensors.mems_microphone.is_recording:
            return jsonify({
                "status": "error",
                "message": "Cannot disconnect the MEMS microphone while recording.",
            }), 409
        sensors.mems_microphone.disconnect()
        sensors.mems_microphone = None
    runtime_config.set_value('mems_enabled', False)
    return jsonify({"status": "ok", "state": "off"})

@app.route('/device-status', methods=['GET'])
def device_status():
    status = {
        "usg": {
            "enabled": runtime_config['usg_enabled'],
            "initialized": bool(sensors.usg_scanner and sensors.usg_scanner.init_success)
        },
        "tracker_imu": {
            "enabled": "imu" in runtime_config['active_trackers'],
            "initialized": "imu" in trackers.active_trackers and getattr(trackers.active_trackers["imu"], 'is_connected', False)
        },
        "tracker_psmove": {
            "enabled": "psmove" in runtime_config['active_trackers'],
            "initialized": "psmove" in trackers.active_trackers and getattr(trackers.active_trackers["psmove"], 'is_connected', False)
        },
        "mems": {
            "enabled": runtime_config['mems_enabled'],
            "initialized": bool(sensors.mems_microphone and sensors.mems_microphone.is_connected
            ),
        }
    }
    return jsonify(status)

@app.route("/run", methods=["POST"])
def run():
    global automation_thread, stop_event
    print("Received run/POST request")
    params = request.get_json(force=True)
    print(f'With params: {params}')

    required = ("speed", "iterations", "points")
    if not all(param in params for param in required):
        return jsonify({"error": "Missing parameters"}), 400
    
    stop_event.clear()
    automation_thread = threading.Thread(
        target=safe_run_automation,
        kwargs=dict(
            points = params["points"],
            speed = int(params["speed"]),
            description = params.get("description", ""),
            num_iterations = int(params["iterations"]),
            num_repetitions = int(params.get("repetitions", 1)),
            initial_sleep_time = int(params.get("initialSleepTime", 3)),
            sleep_time = int(params.get("sleepTime", 3)),
            stop_event = stop_event,
            socketio_instance=socketio
        ),
        daemon=True
    )

    automation_thread.start()

    return jsonify({"status": "started"})

@app.route("/stop", methods=['POST'])
def stop():
    print("Received stop/POST request")
    stop_event.set()
    return jsonify({"status": "Will stop after current iteration."})

@app.route("/start-manual", methods=['POST'])
def start_manual():
    print("Received start-manual/POST request")
    params = request.get_json(force=True)
    description = params.get("description")
    username = params.get("username")
    
    prefix = build_filename(username, description)
    
    success, msg = start_recording(prefix, socketio)
    if success:
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": msg}), 500

@app.route("/stop-manual", methods=['POST'])
def stop_manual():
    print("Received stop-manual/POST request")
    success, message = stop_recording(socketio)
    if not success:
        return jsonify({"status": "error", "message": message}), 500
    return jsonify({"status": "ok"})

@app.route('/delete-last-recording', methods=['POST'])
def post_delete_last_recording():
    print("Received delete-last-recording/POST request")
    
    message = delete_last_recording()
    if message == "":
        return jsonify({"status": "not found", "message": "No recordings to delete."})
    return jsonify({"status": "ok", "message": message})

def parse_args():
    parser = argparse.ArgumentParser(description="Web browser interface for synchronous acquisition of audio "
                                                 "(from rasberry_pi/banana_pi devboard) and video from webcam")
    parser.add_argument("--setup", help="Path to setup JSON file (if not provided or some fields are missing, default "
                                        "configuration is used.)", default="")
    parser.add_argument("--port", type=int, help="Port (default 5000)", default=5000)
    return parser.parse_args()

def main():
    args = parse_args()

    if args.setup:
        config.load_from_json(args.setup)

    port = args.port
    url = "http://127.0.0.1:{0}".format(port)

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    
    try:
        socketio.run(app, port=port, debug=False)
    except KeyboardInterrupt:
        print("KeyboardInterrupt received. Shutting down...")
    finally:
        if sensors.usg_scanner and sensors.usg_scanner.is_initialized:
            sensors.usg_scanner.stop()
        for t in trackers.active_trackers.values():
            if getattr(t, 'is_connected', False) or getattr(t, 'running', False):
                t.stop()
        if sensors.mems_microphone:
            if sensors.mems_microphone.is_recording:
                sensors.mems_microphone.kill_recording()
            sensors.mems_microphone.disconnect()
        os._exit(0)

if __name__ == '__main__':
    main()

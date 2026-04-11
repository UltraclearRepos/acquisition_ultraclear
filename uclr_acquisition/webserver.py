import eventlet
eventlet.monkey_patch()

import numpy as np
import cv2
import base64
from flask import Flask, request, jsonify, send_from_directory
from vnav_acquisition.comm import is_ssh_connected, ssh_connect, on_rec_start, on_rec_stop, start_live_data_stream, stop_live_data_stream
from vnav_acquisition.config import config
from vnav_acquisition.runtime_config import runtime_config
from vnav_acquisition.automation import safe_run_automation
from .record import start_recording, stop_recording, delete_last_recording
from .utils import build_filename, get_local_ip_address
from .track_position import detect_cube_pose
import threading
import webbrowser
import argparse
import os   # Berke 16.09.2024
from pathlib import Path
from flask_socketio import SocketIO
import sounddevice as sd
import time


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR
IP_FILE = BASE_DIR / "pc_ip.txt"

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

    return jsonify({"status": "ok", "filename": filename})


@app.route("/", methods=['GET'])
def frontpage():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/config", methods=['GET'])
def api_config():
    print("Received config/GET request")
    return jsonify({
        "materials": config["materials"],
        "speeds": config["speeds"],
        "needleTypes": config["needleTypes"],
        "sensorVersions": config["sensorVersions"]
    })

@app.route("/run", methods=["POST"])
def run():
    global automation_thread, stop_event
    print("Received run/POST request")
    params = request.get_json(force=True)
    print(f'With params: {params}')

    required = ("material", "speed", "needleType", "iterations", "initX", "finishX", "upZ", "downZ", "motionType")
    if not all(param in params for param in required):
        return jsonify({"error": "Missing parameters"}), 400
    
    stop_event.clear()
    automation_thread = threading.Thread(
        target=safe_run_automation,
        kwargs=dict(
            material = params["material"],
            needle_type = params["needleType"],
            microphone_type = params["microphoneType"],
            description = params["description"],
            stop_event = stop_event,
            initX = params["initX"],
            finishX = params["finishX"],
            upZ = params["upZ"],
            downZ = params["downZ"],
            y = params["y"],
            r = params["r"],
            speed = int(params["speed"]),
            motion_type = params["motionType"],
            num_iterations = params["iterations"],
            interval = params["interval"],
            sleep_time = params["sleepTime"],
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


@app.route("/raspberry-status", methods=['GET'])
def check_connection():
    import logging
    werkzeug_log = logging.getLogger('werkzeug')
    prev_level = werkzeug_log.level
    werkzeug_log.setLevel(logging.ERROR)

    try:
        is_connected = is_ssh_connected()
        if is_connected:
            return jsonify({"status": "connected"})
        else:
            return jsonify({"status": "not connected"})
    finally:
        werkzeug_log.setLevel(prev_level)

@app.route("/set-micro-output", methods=['POST'])
def set_micro_output():
    print("Received set-micro-output/POST request")
    params = request.get_json(force=True)
    print(f'With params: {params}')
    output_name = params.get("micro_output")

    if not output_name:
        return jsonify({"error": "Missing 'micro_output' parameter"}), 400
    
    if output_name == "No Audio":
        runtime_config.set_value('micro_output', None)
    else:
        for idx, dev in enumerate(sd.query_devices()):
            if output_name in dev['name'] and dev['max_output_channels'] > 0:
                runtime_config.set_value('micro_output', idx)
                return jsonify({"status": "ok", "micro_output": idx})
        
    return jsonify({"error": f"Audio output '{output_name}' not found"}), 404

@app.route('/get-audio-outputs', methods=['GET'])
def get_audio_outputs():
    print("Received get-audio-outputs/GET request")
    seen = set()
    outputs = []
    default_hostapi = sd.default.hostapi

    for idx, dev in enumerate(sd.query_devices()):
        name = dev['name'].strip()
        if (dev['max_output_channels'] > 0 
            and name 
            and name not in seen
            and dev['hostapi'] == default_hostapi):
            outputs.append({'name': name})
            seen.add(name)

    outputs.insert(0, {'name': 'No Audio'})

    print(f"Available audio outputs: {outputs}")
    return jsonify(outputs)

@app.route('/start-recording', methods=['POST'])
def post_start_recording():
    print("Received start-recording/POST request")

    params = request.get_json(force=True)
    print(f'With params: {params}')

    username = params.get("username")
    material = params.get("material")
    needle_type = params.get("needleType")
    microphone_type = params.get("microphoneType")
    description = params.get("description")
    output_filename_prefix = build_filename(username, description, material, needle_type, microphone_type)

    is_started = start_recording(output_filename_prefix, socketio)
    if not is_started:
        return jsonify({"error": "Recording could not be started"}), 400
    
    return jsonify({"status": "ok"})


@app.route('/stop-recording', methods=['POST'])
def post_stop_recording():
    print("Received stop-recording/POST request")
    
    stop_recording(socketio)
    return jsonify({"status": "ok"})

@app.route('/delete-last-recording', methods=['POST'])
def post_delete_last_recording():
    print("Received delete-last-recording/POST request")
    
    message = delete_last_recording()
    if message == "":
        return jsonify({"status": "not found", "message": "No recordings to delete."})
    return jsonify({"status": "ok", "message": message})

@app.route('/detect-cube', methods=['POST'])
def detect_cube():

    buffer = request.files["frame"].read()
    buffer_arr = np.frombuffer(buffer, dtype=np.uint8)
    frame = cv2.imdecode(buffer_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return jsonify({"error": "Invalid image data"}), 400

    res = detect_cube_pose(frame)
    if res is None:
        return jsonify({"detected": False})
    
    rvec, tvec, R_inv, corners, ids, init_frame = res

    ok, jpg = cv2.imencode(".jpg", init_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
    if not ok:
        return jsonify({"error": "Could not encode image"}), 500

    data_url = "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode('utf-8')

    return jsonify({
        "detected": True,
        "image": data_url
    })

@app.route('/set-micro-filter', methods=['POST'])
def set_filter_settings():
    print("Received set-micro-filter/POST request")
    params = request.get_json(force=True)
    print(f'With params: {params}')

    enabled = params.get("enabled")
    low = params.get("low")
    high = params.get("high")

    runtime_config.set_value('micro_bandpass_enabled', enabled)
    runtime_config.set_value('micro_bandpass_low', low)
    runtime_config.set_value('micro_bandpass_high', high)
    
    return jsonify({"status": "ok"})

@app.route('/start-stream', methods=['POST'])
def start_stream():
    print("Received start-stream/POST request")
    try:
        start_live_data_stream(config['connection'], socketio)
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Error starting live data stream: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/stop-stream', methods=['POST'])
def stop_stream():
    try:
        stop_live_data_stream(config['connection'], socketio)
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Error stopping live data stream: {e}")
        return jsonify({"error": str(e)}), 500
    

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
    IP_FILE.write_text(get_local_ip_address())

    ssh_connect(*config['connection'], socketio_instance=socketio)

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    
    socketio.run(app, port=port, debug=False)


if __name__ == '__main__':
    main()
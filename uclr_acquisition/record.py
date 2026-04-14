from .config import config
from uclr_acquisition import sensors
import time
import os

filename_prefix = None

def start_recording(output_filename_prefix, socketio_instance):
    global filename_prefix
    filename_prefix = output_filename_prefix

    video_filename = f"{output_filename_prefix}.mp4"

    socketio_instance.emit("record", {
        "action": "start",
        "filename": video_filename
    })

    # is_started = True
    # if not is_started:
    #     socketio_instance.emit("record", {
    #         "action": "stop",
    #         "shouldUpload": False
    #     })
    #     return False
    if sensors.usg_scanner and sensors.usg_scanner.is_initialized:
        sensors.usg_scanner.start_recording()
    
    return True

def stop_recording(socketio_instance):
    global filename_prefix
    
    if sensors.usg_scanner and sensors.usg_scanner.is_initialized and filename_prefix:
        os.makedirs("usg", exist_ok=True)
        usg_video_path = os.path.join("usg", f"{filename_prefix}.mp4")
        sensors.usg_scanner.stop_recording(usg_video_path)

    time.sleep(0.3)
    socketio_instance.emit("record", {
        "action": "stop",
        "shouldUpload": True
    })
    filename_prefix = None

def kill_recording(socketio_instance):
    global filename_prefix
    socketio_instance.emit("record", {
        "action": "stop",
        "shouldUpload": False
    })
    if sensors.usg_scanner and sensors.usg_scanner.is_initialized:
        sensors.usg_scanner.kill_recording()
    filename_prefix = None


def delete_last_recording():
    videos_deleted = delete_videos(folder='videos')
    usg_deleted = delete_usg(folder="usg")

    parts = []
    if videos_deleted:
        parts.append("Video")
    if usg_deleted:
        parts.append("USG")
    
    return " + ".join(parts) if parts else ""

def delete_videos(folder):
    files = {}
    for file in os.listdir(folder):
        parts = file.split("_")
        time_part = parts[-3] + "." + parts[-2]
        timestamp = time.strptime(time_part, '%Y-%m-%d.%H.%M.%S')
        file_path = os.path.join(folder, file)
        files.setdefault(timestamp, []).append(file_path)

    if not files:
        return False

    latest_timestamp = max(files.keys())
    if len(files[latest_timestamp]) == 0:
        return False
    
    for file in files[latest_timestamp]:
        os.remove(file)

    return True


def delete_usg(folder):
    files = {}
    for file in os.listdir(folder):
        parts = file.split("_")
        time_part = parts[-2] + "." + ".".join(parts[-1].split(".")[:3])
        timestamp = time.strptime(time_part, '%Y-%m-%d.%H.%M.%S')
        file_path = os.path.join(folder, file)
        files.setdefault(timestamp, []).append(file_path)

    if not files:
        return False

    latest_timestamp = max(files.keys())
    if len(files[latest_timestamp]) == 0:
        return False
    
    for file in files[latest_timestamp]:
        os.remove(file)

    return True

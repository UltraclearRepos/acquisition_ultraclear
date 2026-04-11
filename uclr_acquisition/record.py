from .comm import on_rec_start, on_rec_stop
from .config import config
import time
import os

def start_recording(output_filename_prefix, socketio_instance):

    video_filename = f"{output_filename_prefix}.mp4"
    audio_filename = f"{output_filename_prefix}.wav"

    socketio_instance.emit("record", {
        "action": "start",
        "filename": video_filename
    })

    is_started = on_rec_start(config['connection'], socketio_instance, audio_filename)
    # is_started = True
    if not is_started:
        socketio_instance.emit("record", {
            "action": "stop",
            "shouldUpload": False
        })
        return False
    
    return True

def stop_recording(socketio_instance):
    is_recorded = on_rec_stop()
    # is_recorded = True
    if not is_recorded:
        socketio_instance.emit("record", {
            "action": "stop",
            "shouldUpload": False
        })
    else:
        time.sleep(0.5)
        socketio_instance.emit("record", {
            "action": "stop",
            "shouldUpload": True
        })

def delete_last_recording():
    videos_deleted = delete_videos(folder='videos')
    audios_deleted = delete_audios(folder=config['local_dir'])

    parts = []
    if videos_deleted:
        parts.append("Video")
    if audios_deleted:
        parts.append("Audio")
    
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


def delete_audios(folder):
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

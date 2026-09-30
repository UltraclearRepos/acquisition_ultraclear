from .config import config
from uclr_acquisition import sensors, trackers
from uclr_acquisition.runtime_config import runtime_config
from uclr_acquisition.sound import play_chirp_signal
import time
import os
import threading

filename_prefix = None
CAMERA_UPLOAD_TIMEOUT_SECONDS = 120

camera_uploads_finished = threading.Event()
camera_upload_success = True
camera_upload_message = None
camera_upload_recording_id = None

def start_recording(output_filename_prefix, socketio_instance):
    global filename_prefix

    unavailable = []
    
    # Check USG if enabled
    if runtime_config['usg_enabled']:
        if not sensors.usg_scanner or not sensors.usg_scanner.is_initialized:
            unavailable.append("USG")
            
    # Check Trackers if enabled
    for t_type in runtime_config['active_trackers']:
        if t_type not in trackers.active_trackers or not getattr(trackers.active_trackers[t_type], 'is_connected', False):
            unavailable.append(f"{t_type.upper()} Tracker")

    if runtime_config['mems_enabled']:
        if not sensors.mems_microphone or not sensors.mems_microphone.is_connected:
            unavailable.append("Raspberry Pi MEMS microphone")

    if unavailable:
        msg = ", ".join(unavailable) + " enabled but not initialized/connected"
        print(f"Recording blocked: {msg}")
        return False, msg

    filename_prefix = output_filename_prefix

    prepare_camera_upload_wait(output_filename_prefix)

    video_filename = f"{output_filename_prefix}.webm"

    if runtime_config['usg_enabled'] and sensors.usg_scanner:
        sensors.usg_scanner.start_recording()

    for t_type in runtime_config['active_trackers']:
        if t_type in trackers.active_trackers:
            trackers.active_trackers[t_type].start_recording()

    mems_started = False
    if sensors.mems_microphone:
        try:
            sensors.mems_microphone.start_recording(
                f"{output_filename_prefix}.wav"
            )
            mems_started = True
        except Exception as exc:
            print(f"Failed to start MEMS recording: {exc}")
            kill_recording(socketio_instance)
            return False, str(exc)

    time.sleep(0.3)

    socketio_instance.emit("record", {
        "action": "start",
        "filename": video_filename,
        "recordingId": output_filename_prefix
    })

    time.sleep(0.3)
    if mems_started and not play_chirp_signal():
        error = "The synchronization chirp could not be played."
        print(error)
        kill_recording(socketio_instance)
        return False, error

    return True, None

def stop_recording(socketio_instance):
    global filename_prefix

    recording_id = filename_prefix

    socketio_instance.emit("record", {
        "action": "stop",
        "shouldUpload": True,
        "recordingId": recording_id
    })
    time.sleep(0.3)

    mems_error = None
    if runtime_config['mems_enabled']:
        if not sensors.mems_microphone or not sensors.mems_microphone.is_connected:
            mems_error = (
                "Raspberry Pi MEMS microphone connection was lost "
                "during recording."
            )
            print(mems_error)
        else:
            try:
                sensors.mems_microphone.stop_capture()
            except Exception as exc:
                mems_error = str(exc)
                print(f"Failed to stop MEMS recording: {exc}")

    if sensors.usg_scanner and sensors.usg_scanner.is_initialized:
        os.makedirs("usg", exist_ok=True)
        os.makedirs("usg_timestamps", exist_ok=True)
        usg_video_path = os.path.join("usg", f"{filename_prefix}.mp4")
        usg_timestamp_path = os.path.join("usg_timestamps", f"{filename_prefix}.csv")
        sensors.usg_scanner.stop_recording(usg_video_path, usg_timestamp_path)

    for t in trackers.active_trackers.values():
        if getattr(t, 'is_connected', False):
            t.stop_recording(filename_prefix)

    if (runtime_config['mems_enabled']
        and sensors.mems_microphone
        and sensors.mems_microphone.is_connected
        and mems_error is None):
        try:
            sensors.mems_microphone.download_recording()
        except Exception as exc:
            mems_error = str(exc)
            print(f"Failed to download MEMS recording: {exc}")

    camera_ok, camera_error = wait_for_camera_uploads()

    errors = []

    if mems_error:
        errors.append(mems_error)

    if not camera_ok:
        errors.append(camera_error)

    filename_prefix = None

    if errors:
        return False, "; ".join(errors)

    return True, None

def kill_recording(socketio_instance):
    global filename_prefix
    socketio_instance.emit("record", {
        "action": "stop",
        "shouldUpload": False,
        "recordingId": filename_prefix
    })
    if sensors.usg_scanner and sensors.usg_scanner.is_initialized:
        sensors.usg_scanner.kill_recording()
    for t in trackers.active_trackers.values():
        if getattr(t, 'is_connected', False):
            t.kill_recording()
    if sensors.mems_microphone:
        sensors.mems_microphone.kill_recording()
    filename_prefix = None


def prepare_camera_upload_wait(recording_id):
    global camera_upload_success
    global camera_upload_message
    global camera_upload_recording_id

    camera_upload_recording_id = recording_id
    camera_upload_success = True
    camera_upload_message = None
    camera_uploads_finished.clear()

def notify_camera_upload_complete(recording_id, success, message=None):
    global camera_upload_success
    global camera_upload_message

    if recording_id != camera_upload_recording_id:
        return False

    camera_upload_success = bool(success)
    camera_upload_message = message
    camera_uploads_finished.set()
    return True

def wait_for_camera_uploads():
    completed = camera_uploads_finished.wait(timeout=CAMERA_UPLOAD_TIMEOUT_SECONDS)

    if not completed:
        return False, "Camera uploads did not complete within the expected time."

    if not camera_upload_success:
        return False, camera_upload_message or "Camera uploads failed."

    return True, None


def delete_last_recording():
    all_files = {}

    def scan_folder(folder, is_suffix_type):
        if not os.path.exists(folder):
            return
        for file in os.listdir(folder):
            parts = file.split("_")
            try:
                if is_suffix_type:
                    time_part = parts[-3] + "." + parts[-2]
                else:
                    time_part = parts[-2] + "." + ".".join(parts[-1].split(".")[:3])
                timestamp = time.strptime(time_part, '%Y-%m-%d.%H.%M.%S')
                file_path = os.path.join(folder, file)
                all_files.setdefault(timestamp, []).append((folder, file_path))
            except Exception:
                pass

    scan_folder('videos', True)
    for f in ['usg', 'usg_timestamps', 'video_timestamps', 'dobot', 'imu', 'psmove']:
        scan_folder(f, False)
    audio_folder = config["local_dir"]
    scan_folder(audio_folder, False)

    if not all_files:
        return ""

    latest_timestamp = max(all_files.keys())
    files_to_delete = all_files[latest_timestamp]

    deleted_folders = set()
    for folder, file_path in files_to_delete:
        try:
            os.remove(file_path)
            deleted_folders.add(folder)
        except OSError:
            pass

    parts = []
    folder_mapping = {
        'videos': 'Video',
        'usg': 'USG',
        'video_timestamps': 'VideoTimestamps',
        'usg_timestamps': 'USGTimestamps',
        'dobot': 'Dobot',
        'imu': 'IMU',
        'psmove': 'PSMove',
        audio_folder: 'MEMSAudio',
    }
    
    for f in [
            'videos', 'usg', 'video_timestamps', 'usg_timestamps',
            'dobot', 'imu', 'psmove', audio_folder]:
        if f in deleted_folders:
            parts.append(folder_mapping[f])
            
    return " + ".join(parts) if parts else ""

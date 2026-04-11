import os
import time
import paramiko
from .sound import play_chirp_signal
from .clean import clean_wav
from .config import config
from .live_audio_data import listen_for_micro_signals, start_micro_signal_sending, is_micro_signal_thread_active, stop_micro_signal_event, micro_signal_thread
import threading

MIC_NAME = "dmic_sv_shared"
CHANNEL_FMT = "stereo"
SAMPLING_RATE = 48000

ssh: paramiko.SSHClient = None
file_name = ""

def is_ssh_connected():
    global ssh
    if ssh is not None and ssh.get_transport() and ssh.get_transport().is_active():
        return True
    return False


def ssh_connect(hostname, port, username, password, socketio_instance):
    global ssh
    try:
        ssh = paramiko.SSHClient()
        print(config['connection'])
        print("Connecting to RaspberryPi...")
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname, port, username, password, timeout=10)
        if not ssh.get_transport() or not ssh.get_transport().is_active():
            ssh = None
            print("SSH transport is not active.")
            return

        print('CONNECTED TO RASPBERRYPI')
    except Exception as e:
        print("SSH connection error:", e)
        ssh = None
        return

    try:
        with ssh.open_sftp() as sftp:
            sftp.put(os.path.join(os.path.dirname(__file__), "asoundrc.txt"), "/home/pi/.asoundrc")
            sftp.put(os.path.join(os.path.dirname(__file__), "pc_ip.txt"), "/home/pi/pc_ip.txt")
            sftp.put(os.path.join(os.path.dirname(__file__), "micro_signal_sender.py"), "/home/pi/micro_signal_sender.py")
            print(f"SFPT setup upload completed.")
    except Exception as e:
        print(f"SFPT setup upload error.", e)
        ssh = None
        return

def on_rec_start(connection, socketio_instance, output_filename):
    print("Executing 'on_rec_start': Starting micro on needle")
    global ssh
    global file_name

    file_name = output_filename

    if ssh is None:
        ssh_connect(*connection, socketio_instance=socketio_instance)
        time.sleep(1)

    if ssh:
        print("Recording started")
        remote_path = f"{config['remote_dir']}/{file_name}"
        mkdir_commad = f"mkdir {os.path.dirname(remote_path)}"
        ssh.exec_command(mkdir_commad)

        setup_command = f"echo 'DEVICE={MIC_NAME}\nDURATION=10\nSAMPLE_RATE={SAMPLING_RATE}\n" \
                        f"CHANNELS=2\nOUTPUT_FILE={remote_path}\nFORMAT=S32_LE' > " \
                        f"{config['remote_dir']}/recording_setup.txt"
        print("Setup command ====================================================================== \n")
        print(setup_command)
        ssh.exec_command(setup_command)
        time.sleep(0.01)

        start_command = f"bash -c 'source {config['remote_dir']}/recording_setup.txt && nohup arecord " \
                        f"-D $DEVICE -r $SAMPLE_RATE -c $CHANNELS -f $FORMAT -t wav -V {CHANNEL_FMT} " \
                        f"$OUTPUT_FILE &'"
        print("Start command ===================================================================== \n")
        print(start_command)
        ssh.exec_command(start_command)
        time.sleep(0.2)
        play_chirp_signal()
    else:
        return False
    
    return True

def kill_rasp_process():
    if ssh is not None:
        print("Killing process on RaspberryPi")
        stop_command = f"kill -INT $(ps aux | grep '[a]record -D {MIC_NAME}' | awk '{{print $2}}')"
        ssh.exec_command(stop_command)

def on_rec_stop(delete=False):
    global ssh
    global file_name
    recorded_files = []
    if ssh is not None:
        print("Recording stopped on RaspberryPi")
        stop_command = f"kill -INT $(ps aux | grep '[a]record -D {MIC_NAME}' | awk '{{print $2}}')"
        ssh.exec_command(stop_command)

        remote_path = f"{config['remote_dir']}/{file_name}"
        local_path = os.path.join(config["local_dir"], file_name)
        os.makedirs(config["local_dir"], exist_ok=True)

        try:
            with ssh.open_sftp() as sftp:
                sftp.get(remote_path, local_path)
        except Exception as e:
            print(f"SFPT download error. (remote '{remote_path}', local '{local_path}'.", e)

        recording_status = os.path.isfile(local_path) and os.path.getsize(local_path)

        if delete:
            delete_command = f"rm {remote_path}"
            ssh.exec_command(delete_command)
    else:
        print("SSH not connected during stopping recording")
        return False
    
    return recording_status


def delete_last_recording():
    global file_name
    deleted = []
    for file in [file_name, file_name[:-len(".wav")] + ".raw.wav"]:
        file = os.path.join(config["local_dir"], file)
        if os.path.exists(file):
            os.remove(file)
            deleted.append(file)
            print(file, "deleted")
        else:
            print(file, "does not exist")
    return deleted

def start_live_data_stream(connection, socketio_instance):
    global ssh

    if ssh is None:
        ssh_connect(*connection, socketio_instance=socketio_instance)
        time.sleep(1)

    if is_micro_signal_thread_active():
        stop_micro_signal_event.set()
        micro_signal_thread.join(timeout=5)
        if micro_signal_thread.is_alive():
            print("Warning: micro_signal_thread did not stop in time")

    # Clear the stop event before starting new thread
    stop_micro_signal_event.clear()

    # Start listener thread (it will start receiver thread and update micro_signal_thread)
    threading.Thread(
        target=listen_for_micro_signals,
        args=(socketio_instance,),
        daemon=True
    ).start()

    time.sleep(1)
    start_micro_signal_sending(ssh)

def stop_live_data_stream(connection, socketio_instance):
    global ssh

    stop_micro_signal_event.set()

    if ssh is None:
        ssh_connect(*connection, socketio_instance=socketio_instance)
        time.sleep(1)

    try:
        ssh.exec_command("pkill -INT -f /home/pi/micro_signal_sender.py >/dev/null 2>&1 || true")
        ssh.exec_command("pkill -TERM -f /home/pi/micro_signal_sender.py >/dev/null 2>&1 || true")
    except Exception as e:
        print("Error stopping micro signal sender:", e)

    if micro_signal_thread is not None and micro_signal_thread.is_alive():
        micro_signal_thread.join(timeout=5)


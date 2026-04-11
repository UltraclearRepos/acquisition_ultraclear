import os
import socket
import threading
import queue
import time
import numpy as np
import sounddevice as sd
from .runtime_config import runtime_config
import platform
from scipy.signal import butter, sosfilt, sosfilt_zi

micro_signal_thread = None
stop_micro_signal_event = threading.Event()

FRAMES_PER_PACKET = 512
BYTES_PER_SAMPLE = 4
CHANNELS = 2
BYTES_PER_FRAME = CHANNELS * BYTES_PER_SAMPLE
PACKET_BYTES = FRAMES_PER_PACKET * BYTES_PER_FRAME
BATCH_FRAMES = 4
BATCH_BYTES = BATCH_FRAMES * PACKET_BYTES
SAMPLE_RATE = 48000
PACKET_PERIOD_SEC = FRAMES_PER_PACKET / SAMPLE_RATE

def _win_timer_high_res(enable=True):
    try:
        import ctypes
        if enable:
            ctypes.windll.winmm.timeBeginPeriod(1)
        else:
            ctypes.windll.winmm.timeEndPeriod(1)
    except Exception:
        pass

def is_micro_signal_thread_active():
    global micro_signal_thread
    return micro_signal_thread is not None and micro_signal_thread.is_alive()

def start_micro_signal_sending(ssh):
    print("Starting micro signal sending on RaspberryPi")
    command = "python3 -u /home/pi/micro_signal_sender.py"
    ssh.exec_command(command)

    # import subprocess, sys
    # wav_path = r"C:\Users\jakub\Desktop\ncn\acquisition\record.wav"

    # script_path = os.path.join(os.path.dirname(__file__), "micro_signal_sender_file.py")
    # args = [
    #     sys.executable, "-u", script_path,
    #     "--host", "127.0.0.1",
    #     "--port", "5001",
    #     "--wav", wav_path,
    # ]

    # print("Starting local wav sender:", args)
    # subprocess.Popen(args)

def listen_for_micro_signals(sio):
        global micro_signal_thread
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 5001))
        s.listen(1)
        print("Waiting for connection to micro signal server...")
        s.settimeout(10)
        try:
            conn, addr = s.accept()
            print(f"Connection from {addr}")
            # Create receiver thread - this is the long-running one we want to track
            receiver_thread = threading.Thread(
                target=receive_and_send_micro_signals, 
                args=(conn, sio,), 
                daemon=True
            )
            # Update global reference to the receiver thread (not listener)
            micro_signal_thread = receiver_thread
            receiver_thread.start()
        except socket.timeout:
            print("No connection received within timeout period.")
        finally:
            s.close()

        print("Finished listener thread, receiver thread is now running")

def _make_output_stream(device_index, callback):
    return sd.OutputStream(
        samplerate=SAMPLE_RATE,
        channels=2,
        dtype='float32',
        device=device_index,
        callback=callback,
        latency='low',
        blocksize=FRAMES_PER_PACKET
    )

def clear_queue(audio_queue):
    try:
        while True:
            audio_queue.get_nowait()
    except queue.Empty:
        pass

def start_audio_pacer(buffer_audio, buffer_audio_lock, audio_queue, warmup_state):
    stop_event = threading.Event()

    def pacer_run():
        if platform.system() == 'Windows':
            _win_timer_high_res(True)
        try:
            last_t = time.perf_counter()

            MAX_CATCHUP_PACKETS = 16
            TARGET_BACKLOG_PACKETS = 8
            HARD_BACKLOG_PACKETS = 32

            while not stop_event.is_set():
                now = time.perf_counter()
                elapsed = now - last_t

                if elapsed < PACKET_PERIOD_SEC * 0.9:
                    rem = PACKET_PERIOD_SEC - elapsed
                    if rem > 0.002:
                        time.sleep(0.001)
                    else:
                        while(PACKET_PERIOD_SEC - (time.perf_counter() - last_t)) > 0:
                            pass
                    continue
                
                backlog_packets = len(buffer_audio) // PACKET_BYTES
                free_slots = audio_queue.maxsize - audio_queue.qsize()
                should_emit = int(elapsed / PACKET_PERIOD_SEC)
                extra = max(0, backlog_packets - TARGET_BACKLOG_PACKETS)
                to_emit = min(should_emit + extra, MAX_CATCHUP_PACKETS, free_slots, backlog_packets)

                emitted = 0
                while emitted < to_emit:
                    with buffer_audio_lock:
                        backlog_bytes = len(buffer_audio)
                        hard_limit_bytes = HARD_BACKLOG_PACKETS * PACKET_BYTES
                        target_bytes = TARGET_BACKLOG_PACKETS * PACKET_BYTES
                        if backlog_bytes > hard_limit_bytes:
                            drop = backlog_bytes - target_bytes
                            print(f'Limit in buffer audio reached, dropping {drop} bytes')
                            del buffer_audio[:drop]
                            backlog_bytes = len(buffer_audio)

                        if backlog_bytes >= PACKET_BYTES:
                            pkt = bytes(buffer_audio[:PACKET_BYTES])
                            del buffer_audio[:PACKET_BYTES]
                        else:
                            pkt = None

                    if pkt is None:                        
                        break

                    arr = np.frombuffer(pkt, dtype='<i4').reshape(-1, 2)
                    block = (arr / (2**31)).astype(np.float32)
                    try:
                        audio_queue.put(block, timeout=0.002)
                    except queue.Full:
                        try:
                            print(f'Audio queue is full, dropping oldest packet')
                            audio_queue.get_nowait()
                            audio_queue.put(block, timeout=0.002)
                        except queue.Empty:
                            pass
                        except queue.Full:
                            pass

                    emitted += 1

                if(to_emit == 0):
                    last_t = now
                else:
                    last_t += should_emit * PACKET_PERIOD_SEC

                if not warmup_state["done"]:
                    if audio_queue.qsize() >= warmup_state["target_elements"]:
                        warmup_state["done"] = True
                        print("Warmup done, audio queue is ready.")

        finally:
            if platform.system() == 'Windows':
                _win_timer_high_res(False)

    t = threading.Thread(target=pacer_run, daemon=True)
    t.start()
    return t, stop_event

def receive_and_send_micro_signals(conn, sio):
    global stop_micro_signal_event

    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(2.0)
    except Exception as e:
        pass

    buffer_audio = bytearray()
    buffer_data = bytearray()
    buffer_audio_lock = threading.Lock()

    audio_queue = queue.Queue(maxsize=8)
    warmup_state = {"done": False, "target_elements": 4}

    leftover = np.zeros((0, 2), dtype=np.float32)
    def audio_callback(outdata, frames, time_info, status):
        nonlocal leftover

        if not warmup_state["done"]:
            outdata[:] = 0.0
            return
        
        needed = frames
        write_pos = 0

        if leftover.shape[0] > 0:
            take = min(needed, leftover.shape[0])
            outdata[:take, :] = leftover[:take, :]
            write_pos += take
            needed -= take

            if take < leftover.shape[0]:
                leftover = leftover[take:, :]
            else:
                leftover = np.zeros((0, 2), dtype=np.float32)

        while needed > 0:
            try:
                block = audio_queue.get_nowait()
            except queue.Empty:
                print("Audio queue is empty, filling with silence. Start warming up")
                outdata[write_pos:frames, :] = 0.0
                warmup_state["done"] = False
                return
            
            if block.shape[0] <= needed:
                outdata[write_pos:write_pos + block.shape[0], :] = block
                write_pos += block.shape[0]
                needed -= block.shape[0]
            else:
                outdata[write_pos:write_pos + needed, :] = block[:needed, :]
                leftover = block[needed:, :]
                return


    current_output_index = None
    output_stream = None
    pacer_thread = None
    pacer_stop = None
    try:
        while True:
            if stop_micro_signal_event.is_set():
                break

            try:
                data = conn.recv(16384)
            except socket.timeout:
                # Timeout allows us to check stop_event periodically
                continue
            
            if not data:
                break

            new_index = runtime_config['micro_output']
            if new_index != current_output_index:

                if pacer_thread:
                    if pacer_stop:
                        pacer_stop.set()
                    try:
                        pacer_thread.join(timeout=0.5)
                    except Exception as e:
                        pass

                    pacer_thread = None
                    pacer_stop = None

                if output_stream:
                    try:
                        output_stream.stop()
                        output_stream.close()
                    except Exception as e:
                        pass
                    output_stream = None

                warmup_state["done"] = False
                leftover = leftover[:0, :]
                clear_queue(audio_queue)
                with buffer_audio_lock:
                    buffer_audio.clear()

                if new_index is not None:
                    try:
                        output_stream = _make_output_stream(new_index, audio_callback)
                        current_output_index = new_index
                        output_stream.start()
                        print(f'Switched micro output to device index: {current_output_index}')

                    except Exception as e:
                        print(f"Error switching micro output: {e}")
                        current_output_index = None
                        output_stream = None

                    pacer_thread, pacer_stop = start_audio_pacer(
                        buffer_audio, buffer_audio_lock, audio_queue, warmup_state
                    )

                else:
                    current_output_index = new_index

            if output_stream:
                with buffer_audio_lock:
                    buffer_audio.extend(data)
            buffer_data.extend(data)

            send_audio_data(buffer_data, sio)

    except Exception as e:
        print(f"Error receiving and sending micro signals: {e}")
    finally:
        if pacer_stop:
            pacer_stop.set()
        if output_stream:
            try:
                output_stream.stop()
                output_stream.close()
            except Exception as e:
                pass
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception as e:
            pass
        try:
            conn.close()
        except Exception as e:
            pass

BP_SOS = None
BP_ZI_L = None
BP_ZI_R = None
BP_LAST_CFG = None

def _build_bandpass_sos(fs, f1, f2, order=4):
    nyq = fs * 0.5
    wl = max(f1 / nyq, 1e-6)
    wh = min(f2 / nyq, 0.999999)
    sos = butter(order, [wl, wh], btype='bandpass', output='sos')
    return sos

def _ensure_bandpass_initialized(fs):
    global BP_SOS, BP_ZI_L, BP_ZI_R, BP_LAST_CFG

    enabled = runtime_config['micro_bandpass_enabled']
    f1 = runtime_config['micro_bandpass_low']
    f2 = runtime_config['micro_bandpass_high']

    current_cfg = (enabled, f1, f2)
    if current_cfg == BP_LAST_CFG and BP_SOS is not None:
        return True
    
    if not enabled:
        BP_SOS = None
        BP_ZI_L = None
        BP_ZI_R = None
        BP_LAST_CFG = current_cfg
        return False
    
    BP_SOS = _build_bandpass_sos(fs, f1, f2, order=25)
    BP_ZI_L = sosfilt_zi(BP_SOS)
    BP_ZI_R = sosfilt_zi(BP_SOS)
    BP_LAST_CFG = current_cfg
    return True

def _apply_bandpass(left, right, fs):
    global BP_SOS, BP_ZI_L, BP_ZI_R

    scale = 2**31
    xL = left.astype(np.float32) / scale
    xR = right.astype(np.float32) / scale

    initialized = _ensure_bandpass_initialized(fs)
    if not initialized:
        return xL.astype('<f4'), xR.astype('<f4')

    yL, BP_ZI_L = sosfilt(BP_SOS, xL, zi=BP_ZI_L)
    yR, BP_ZI_R = sosfilt(BP_SOS, xR, zi=BP_ZI_R)

    return yL.astype('<f4'), yR.astype('<f4')
    

def send_audio_data(buffer, sio):

    while len(buffer) >= BATCH_BYTES:
        batch_bytes = bytes(buffer[:BATCH_BYTES])

        arr = np.frombuffer(batch_bytes, dtype='<i4')
        left = arr[::2]
        right = arr[1::2]

        left, right = _apply_bandpass(left, right, SAMPLE_RATE)

        sio.emit('micro-signal', {
            'left': left.tobytes(),
            'right': right.tobytes()
        })

        del buffer[:BATCH_BYTES]

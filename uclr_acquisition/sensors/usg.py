import threading
import time
import ctypes
from ctypes import c_int32, c_uint32, POINTER
import numpy as np
import cv2

USG_W, USG_H = 512, 512

class USGScanner(threading.Thread):
    def __init__(self, dll_path):
        super().__init__()
        self.daemon = True
        self.w = USG_W
        self.h = USG_H
        self.dll_path = dll_path
        self.running = True
        self.is_recording = False
        self.recorded_frames = [] 
        
        self.black_frame = np.zeros((self.h, self.w), dtype=np.uint8)
        self.latest_frame = self.black_frame.copy()
        self.lock = threading.Lock()
        self.record_start_time = 0
        self.record_stop_time = 0
        
        self.is_frozen = True
        self.target_frozen = True
        self.was_frozen = True

        try:
            self.lib = ctypes.CDLL(self.dll_path)
            self.is_initialized = True
        except OSError:
            try:
                self.lib = ctypes.WinDLL(self.dll_path)
                self.is_initialized = True
            except:
                self.is_initialized = False

        if self.is_initialized:
            self.lib.on_init.restype = None
            self.lib.init_ultrasound_usgfw2.restype = c_int32
            self.lib.find_connected_probe.restype = c_int32
            self.lib.data_view_function.restype = c_int32
            self.lib.mixer_control_function.restype = c_int32
            self.lib.return_pixel_values.restype = None
            self.lib.return_pixel_values.argtypes = [POINTER(c_uint32)]
            self.lib.Run_ultrasound_scanning.restype = None
            self.lib.Freeze_ultrasound_scanning.restype = None
            self.lib.Stop_ultrasound_scanning.restype = None
            self.lib.Close_and_release.restype = None

            self.buf_len = self.w * self.h * 4
            self.BufType = c_uint32 * self.buf_len
            self.p_array = self.BufType()

    def run(self):
        if not self.is_initialized:
            print("Ultrasound could not be started. DLL not loaded.")
            return

        self.lib.on_init()
        if self.lib.init_ultrasound_usgfw2() == 2: return
        if self.lib.find_connected_probe() != 101: return
        if self.lib.data_view_function() < 0: return
        if self.lib.mixer_control_function(0, 0, self.w, self.h, 0, 0, 0) < 0: return
        # Initializing the buffer sequence by running and freezing once physically
        self.lib.Run_ultrasound_scanning()
        time.sleep(0.2)
        self.lib.Freeze_ultrasound_scanning()

        print("Ultrasound initialized in frozen state.")

        while self.running:
            if self.target_frozen != self.is_frozen:
                if self.target_frozen:
                    if self.is_initialized:
                        self.lib.Freeze_ultrasound_scanning()
                    with self.lock:
                        self.latest_frame = self.black_frame.copy()
                    self.is_frozen = True
                else:
                    if self.is_initialized:
                        self.lib.Run_ultrasound_scanning()
                    self.is_frozen = False
                
            if self.is_frozen:
                time.sleep(0.1)
                continue

            self.lib.return_pixel_values(self.p_array)
            np_all = np.ctypeslib.as_array(self.p_array)
            blue = np_all[0::4].astype(np.uint8)
            img_gsc = blue.reshape((self.w, self.h), order='F')
            img = img_gsc[:, ::-1].T

            frame_copy = img.copy()

            if self.is_recording:
                current_time = time.time()
                self.recorded_frames.append((current_time, frame_copy))

            with self.lock:
                self.latest_frame = frame_copy
                    
            time.sleep(0.03)

    def stop(self):
        self.running = False
        if self.is_initialized:
            try: self.lib.Freeze_ultrasound_scanning()
            except: pass
            try: self.lib.Stop_ultrasound_scanning()
            except: pass
            try: self.lib.Close_and_release()
            except: pass
            print("Ultrasound connection closed.")
            
    def turn_on(self):
        """Resumes physical ultrasound scanning"""
        self.target_frozen = False

    def turn_off(self):
        """Freezes physical ultrasound scanning (saves hardware)"""
        if self.is_recording:
            msg = "Stopping blocked - data recording in progress."
            print(f"Skipped: {msg}")
            return False, msg
        self.target_frozen = True
        return True, "Successfully frozen scanning."

    def start_recording(self):
        self.was_frozen = self.target_frozen
        if self.target_frozen:
            self.turn_on()
            
        self.recorded_frames.clear()
        self.record_start_time = time.time()
        self.is_recording = True

    def stop_recording(self, video_path, video_time_path):
        self.is_recording = False
        self.record_stop_time = time.time()
        
        data_len = len(self.recorded_frames)
        total_duration = self.record_stop_time - self.record_start_time
        real_fps = data_len / total_duration if total_duration > 0 else 25.0
        
        print(f"USG Recording saved. {data_len} frames @ {real_fps:.2f} FPS")

        with open(video_time_path, 'w') as f:
            f.write("timestamp,frame_index\n")
            for idx, (timestamp, _) in enumerate(self.recorded_frames):
                f.write(f"{timestamp:.6f},{idx}\n")

        print(f"USG timestamps saved successfully to {video_time_path}")

        if data_len > 0:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(video_path, fourcc, real_fps, (self.w, self.h), isColor=False)
            
            for timestamp, frame in self.recorded_frames:
                out.write(frame) 
                
            out.release()
            print(f"USG Video saved successfully to {video_path}")
        else:
            print("USG Video not saved - no frames captured.")

        if self.was_frozen:
            self.turn_off()

    def kill_recording(self):
        self.is_recording = False
        self.recorded_frames.clear()
        if self.was_frozen:
            self.turn_off()

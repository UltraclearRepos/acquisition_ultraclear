import os
import time
import csv
import threading
import ctypes

class PSMVector3f(ctypes.Structure):
    _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float), ("z", ctypes.c_float)]

class PSMoveTracker(threading.Thread):
    def __init__(self, dll_path, controller_id=1):
        super().__init__(daemon=True)
        self.dll_path = dll_path
        self.controller_id = controller_id
        
        self.output_dir = 'tracker'
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.running = True
        self.is_recording = False
        self.is_connected = False
        self.data_buffer = []

    def connect(self):
        if not os.path.exists(self.dll_path):
            raise Exception(f"PSMove DLL not found at: {self.dll_path}")
            
        os.add_dll_directory(os.path.dirname(self.dll_path))
        try:
            self.psm = ctypes.CDLL(self.dll_path)
            self.psm.PSM_Initialize.restype = ctypes.c_int
            self.psm.PSM_StartControllerDataStream.restype = ctypes.c_int
            self.psm.PSM_GetControllerPosition.argtypes = [ctypes.c_int, ctypes.POINTER(PSMVector3f)]
        except Exception as e:
            raise Exception(f"Failed to load PSMove DLL: {e}")

        if self.psm.PSM_Initialize(b"localhost", b"9512", 1000) != 0:
            raise Exception("PSMove Connection Error! Is PSMoveService running?")

        self.psm.PSM_StartControllerDataStream(self.controller_id, 0x07, 0)
        self.is_connected = True
        print("PSMove Tracker connected and stream started (~100 Hz).")

    def run(self):
        if not self.is_connected:
            print("PSMove not connected.")
            return

        pos = PSMVector3f()
        while self.running:
            self.psm.PSM_Update()
            self.psm.PSM_GetControllerPosition(self.controller_id, ctypes.byref(pos))
            
            if self.is_recording:
                current_time = time.time()
                # PSMove in analyze script was just recording x,y,z
                self.data_buffer.append((current_time, pos.x, pos.y, pos.z))
            
            time.sleep(0.01) # ~100Hz

    def start_recording(self):
        self.data_buffer.clear()
        self.is_recording = True
        print("PSMove recording started.")

    def stop_recording(self, filename):
        self.is_recording = False

        if self.data_buffer:
            output_path = os.path.join(self.output_dir, f"{filename}.csv")
            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Timestamp', 'X', 'Y', 'Z'])
                writer.writerows(self.data_buffer)
            print(f"PSMove data saved to {output_path} ({len(self.data_buffer)} samples)")
            self.data_buffer.clear()
        else:
            print("No PSMove data recorded.")

    def kill_recording(self):
        self.is_recording = False
        self.data_buffer.clear()

    def stop(self):
        self.running = False
        if self.is_connected:
            try:
                self.psm.PSM_Shutdown()
            except:
                pass
            print("PSMove connection closed.")

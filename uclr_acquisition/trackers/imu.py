import serial
import time
import threading
import os
import csv


class IMUTracker(threading.Thread):
    def __init__(self):

        super().__init__(daemon=True)

        self.port = 'COM8'
        self.baudrate = 115200
        self.output_dir = 'tracker'

        self.ser = None
        self.running = True
        self.is_recording = False
        self.is_connected = False
        self.data_buffer = []

        os.makedirs(self.output_dir, exist_ok=True)

    def connect(self):
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=5
            )
            self.ser.reset_input_buffer()
            self.is_connected = True
            print("IMU connected.")
        except Exception as e:
            print(f"IMU connection failed: {e}")
            raise Exception(f"IMU connection failed: {e}")

    def run(self):

        if not self.is_connected:
            print("IMU not connected.")
            return

        while self.running:
            if self.ser.in_waiting > 0:
                try:
                    line_bytes = self.ser.readline()
                    if self.is_recording:
                        recv_time = time.time()

                        line_str = line_bytes.decode('utf-8', errors='ignore').strip()
                        if line_str:
                            self.data_buffer.append((recv_time, line_str))
                except Exception as e:
                    print(f"IMU reading failed: {e}")

                time.sleep(0.05)
            else:
                time.sleep(0.05)

        if self.ser and self.ser.is_open:
            self.ser.close()
            print("IMU disconnected.")

    def start_recording(self):
        self.data_buffer.clear()
        self.is_recording = True
        print("IMU recording started.")

    def stop_recording(self, filename):
        self.is_recording = False

        if self.data_buffer:
            output_path = os.path.join(self.output_dir, f"{filename}.csv")
            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'data'])
                writer.writerows(self.data_buffer)
            print(f"IMU data saved to {output_path} ({len(self.data_buffer)} samples)")
            self.data_buffer.clear()
        else:
            print("No IMU data recorded.")

    def kill_recording(self):
        self.is_recording = False
        self.data_buffer.clear()

    def stop(self):
        self.running = False

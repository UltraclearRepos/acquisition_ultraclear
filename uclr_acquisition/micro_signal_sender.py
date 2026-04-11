import alsaaudio
import socket
import time
import signal

# Handle SIGTERM gracefully (convert to KeyboardInterrupt for clean shutdown)
def handle_sigterm(signum, frame):
    raise KeyboardInterrupt("SIGTERM received")

signal.signal(signal.SIGTERM, handle_sigterm)

def get_server_ip():
    try:
        with open("pc_ip.txt", "r") as f:
            ip = f.read().strip()
            if ip:
                return ip
    except FileNotFoundError:
        print("pc_ip.txt not found")

BROADCAST_PORT = 54545
SERVER_IP = get_server_ip()
PORT = 5001
CHUNK = 512
RATE = 48000
CHANNELS = 2

mic = alsaaudio.PCM(
    type=alsaaudio.PCM_CAPTURE, mode=alsaaudio.PCM_NORMAL,
    device='dmic_sv_shared', channels=CHANNELS, rate=RATE,
    format=alsaaudio.PCM_FORMAT_S32_LE, periodsize=CHUNK
)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect((SERVER_IP, PORT))

try:
    while True:
        l, data = mic.read()
        if l:
            sock.sendall(data)
        else:
            time.sleep(0.01)
except KeyboardInterrupt:
    print("Stopping stream")
finally:
    sock.close()
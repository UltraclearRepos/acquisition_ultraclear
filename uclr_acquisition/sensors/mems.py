import shlex
import time
from pathlib import Path, PurePosixPath

import paramiko

from uclr_acquisition.sound import play_chirp_signal


class MEMSMicrophone:
    """Raspberry Pi MEMS sensor and remote WAV recorder controlled over SSH."""

    DEFAULT_DEVICE = "dmic_sv_shared"
    DEFAULT_SAMPLE_RATE = 48000
    DEFAULT_CHANNELS = 2
    DEFAULT_FORMAT = "S32_LE"

    def __init__(
            self,
            hostname,
            port,
            username,
            password,
            remote_dir,
            local_dir,
            device=DEFAULT_DEVICE,
            sample_rate=DEFAULT_SAMPLE_RATE,
            channels=DEFAULT_CHANNELS,
            sample_format=DEFAULT_FORMAT):
        self.hostname = hostname
        self.port = int(port)
        self.username = username
        self.password = password
        self.remote_dir = PurePosixPath(remote_dir)
        self.local_dir = Path(local_dir)
        self.device = device
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.sample_format = sample_format

        self.ssh = None
        self.remote_pid = None
        self.remote_path = None
        self.local_path = None
        self.is_recording = False

    @property
    def is_connected(self):
        transport = self.ssh.get_transport() if self.ssh is not None else None
        return bool(transport and transport.is_active())

    def connect(self):
        if self.is_connected:
            return

        print(f"Connecting to Raspberry Pi MEMS microphone at {self.hostname}...")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=10,
            )
            self.ssh = client
            self._upload_alsa_config()
        except Exception:
            client.close()
            self.ssh = None
            raise

        print("Raspberry Pi MEMS microphone connected.")

    def disconnect(self):
        if self.is_recording:
            raise RuntimeError(
                "Cannot disconnect the Raspberry Pi microphone while recording."
            )
        if self.ssh is not None:
            self.ssh.close()
        self.ssh = None
        print("Raspberry Pi MEMS microphone disconnected.")

    def _upload_alsa_config(self):
        local_config = Path(__file__).resolve().parent / "asoundrc.txt"
        remote_config = "/home/pi/.asoundrc"
        with self.ssh.open_sftp() as sftp:
            sftp.put(str(local_config), remote_config)
        print(f"Raspberry Pi ALSA configuration uploaded to {remote_config}.")

    def _exec(self, command):
        if not self.is_connected:
            raise RuntimeError("Raspberry Pi microphone is not connected.")
        _, stdout, stderr = self.ssh.exec_command(command)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode("utf-8", errors="replace").strip()
        error = stderr.read().decode("utf-8", errors="replace").strip()
        if exit_code != 0:
            raise RuntimeError(error or output or f"Remote command failed: {command}")
        return output

    def start_recording(self, filename):
        if not self.is_connected:
            raise RuntimeError("Raspberry Pi microphone is not connected.")
        if self.is_recording:
            raise RuntimeError("Raspberry Pi microphone is already recording.")

        self.remote_path = self.remote_dir / filename
        self.local_path = self.local_dir / filename

        remote_parent = shlex.quote(str(self.remote_path.parent))
        remote_path = shlex.quote(str(self.remote_path))
        device = shlex.quote(self.device)
        sample_format = shlex.quote(self.sample_format)
        self._exec(f"mkdir -p {remote_parent}")

        command = (
            f"nohup arecord -D {device} "
            f"-r {self.sample_rate} -c {self.channels} "
            f"-f {sample_format} -t wav -V stereo "
            f"{remote_path} >/tmp/uclr_mems_arecord.log 2>&1 "
            f"</dev/null & echo $!"
        )
        pid_output = self._exec(command)
        try:
            self.remote_pid = int(pid_output.splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise RuntimeError(
                f"Could not determine remote arecord PID: {pid_output!r}"
            ) from exc

        time.sleep(0.2)
        self._exec(f"kill -0 {self.remote_pid}")
        self.is_recording = True
        print(f"MEMS recording started: {self.remote_path}")

        if not play_chirp_signal():
            self.kill_recording()
            raise RuntimeError(
                "MEMS recording started, but the synchronization chirp "
                "could not be played."
            )

    def stop_capture(self):
        """Stop arecord and wait until the WAV header/file is finalized."""
        if not self.is_recording or self.remote_pid is None:
            return

        pid = self.remote_pid
        try:
            self._exec(f"kill -INT {pid}")
        except RuntimeError as exc:
            print(f"Could not signal arecord process {pid}: {exc}")

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, stdout, _ = self.ssh.exec_command(f"kill -0 {pid}")
            if stdout.channel.recv_exit_status() != 0:
                break
            time.sleep(0.1)

        self.is_recording = False
        self.remote_pid = None
        print("MEMS recording stopped on Raspberry Pi.")

    def download_recording(self):
        if self.remote_path is None or self.local_path is None:
            raise RuntimeError("No MEMS recording is available to download.")

        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.ssh.open_sftp() as sftp:
                sftp.get(str(self.remote_path), str(self.local_path))
        except Exception as exc:
            raise RuntimeError(
                f"Could not download MEMS WAV from {self.remote_path} "
                f"to {self.local_path}: {exc}"
            ) from exc

        if not self.local_path.is_file() or self.local_path.stat().st_size <= 44:
            raise RuntimeError(
                f"Downloaded MEMS WAV is empty or invalid: {self.local_path}"
            )

        print(f"MEMS WAV saved to {self.local_path}.")
        return str(self.local_path)

    def stop_recording(self):
        self.stop_capture()
        return self.download_recording()

    def kill_recording(self):
        if self.remote_pid is not None and self.is_connected:
            try:
                self._exec(f"kill -INT {self.remote_pid}")
            except RuntimeError as exc:
                print(f"Could not kill MEMS recording: {exc}")
        self.remote_pid = None
        self.is_recording = False

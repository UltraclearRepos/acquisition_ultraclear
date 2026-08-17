import threading

import numpy as np
import sounddevice as sd


class AudioPlayer:
    """Play one audio channel while keeping it synchronized with video."""

    def __init__(self, audio_data, sample_rate, audio_channel):
        self._stream = None
        self._sample_rate = sample_rate
        self._position = 0
        self._playing = False
        self._lock = threading.Lock()

        if audio_data is None or sample_rate is None:
            return

        if not 0 <= audio_channel < audio_data.shape[0]:
            print(
                f"Audio channel {audio_channel} is unavailable; "
                "audio playback is disabled."
            )
            return

        self._channel_data = audio_data[audio_channel].astype(np.float32)

        def callback(outdata, frames, time_info, status):
            del time_info
            if status:
                print(f"Audio playback status: {status}")

            with self._lock:
                if not self._playing:
                    outdata.fill(0)
                    return

                start = self._position
                end = start + frames
                if start >= len(self._channel_data):
                    self._playing = False
                    outdata.fill(0)
                    return

                valid_end = min(end, len(self._channel_data))
                valid_samples = valid_end - start
                outdata[:valid_samples, 0] = self._channel_data[start:valid_end]
                if valid_samples < frames:
                    outdata[valid_samples:, 0] = 0
                    self._playing = False
                self._position = valid_end

        try:
            self._stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                callback=callback,
                blocksize=1024,
            )
            self._stream.start()
        except Exception as exc:
            print(f"Audio playback error: {exc}")
            self._stream = None

    def play(self, time_in_seconds):
        if self._stream is None:
            return
        with self._lock:
            self._position = int(time_in_seconds * self._sample_rate)
            self._playing = True

    def pause(self):
        if self._stream is None:
            return
        with self._lock:
            self._playing = False

    def seek(self, time_in_seconds):
        if self._stream is None:
            return
        with self._lock:
            self._position = int(time_in_seconds * self._sample_rate)

    def stop(self):
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass

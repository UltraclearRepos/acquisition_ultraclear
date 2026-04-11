import numpy as np
import sounddevice as sd


def generate_chirp_signal(duration=0.2, start_freq=500, end_freq=4000, sample_rate=44100):
    t = np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
    chirp_signal = np.sin(2 * np.pi * np.interp(t, [0, duration], [start_freq, end_freq]) * t)
    return chirp_signal


def play_chirp_signal(delay=0, fs=44100):
    try:
        delayed_chirp_signal = np.hstack((np.zeros(int(delay*fs)), _chirp_signal))
        sd.play(delayed_chirp_signal, fs)
    except Exception as e:
        print(f"Error playing chirp sound: {e}")


_chirp_signal = generate_chirp_signal()

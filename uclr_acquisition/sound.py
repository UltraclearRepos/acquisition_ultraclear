import numpy as np
import sounddevice as sd

from .runtime_config import runtime_config


def generate_chirp_signal(
        duration=0.2,
        start_freq=500,
        end_freq=4000,
        sample_rate=44100):
    """Generate the same synchronization chirp as the VibroNav tool."""
    t = np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
    return np.sin(
        2 * np.pi
        * np.interp(t, [0, duration], [start_freq, end_freq])
        * t
    )


def play_chirp_signal(delay=0, sample_rate=44100):
    """Play the synchronization chirp through the selected PC output."""
    output_device = runtime_config['sync_output']
    if output_device is None:
        print("Synchronization chirp skipped - no output device selected.")
        return True

    try:
        delayed_signal = np.hstack(
            (np.zeros(int(delay * sample_rate)), _CHIRP_SIGNAL)
        )
        sd.play(
            delayed_signal,
            sample_rate,
            device=output_device,
        )
        return True
    except Exception as exc:
        print(f"Error playing synchronization chirp: {exc}")
        return False


_CHIRP_SIGNAL = generate_chirp_signal()

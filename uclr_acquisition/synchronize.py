import argparse
import csv
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate2d, stft

from uclr_acquisition.config import AUDIO_RAW_DIR, CAMERA_VIDEO_DIRS

# One convention for every device:
# delay = device_time - camera_time
# sync_timestamp = timestamp - delay
DOBOT_CAMERA_DELAY_S = -0.080667
USG_CAMERA_DELAY_S = 0.028167
IMU_CAMERA_DELAY_S = 0.015917
PSMOVE_CAMERA_DELAY_S = 0.0

AUDIO_CHANNEL = 0
VIDEO_AUDIO_CHANNEL = 0

# Smaller audio/video offsets are ignored. They are below the chirp detection
# resolution, and the Opus encoder delay (~6.5 ms) is reported as a negative
# audio start time even when the decoded audio starts together with the video.
AUDIO_OFFSET_TOLERANCE_S = 0.01


def read_wave(path):
    sample_rate, x = wavfile.read(path)
    x = x.T
    if x.dtype == np.int32:
        x = x / float(2**31 - 1)
    elif x.dtype == np.int16:
        x = x / float(2**15 - 1)
    if len(x.shape) == 1:
        x = x[None, :]
    return sample_rate, x


def generate_chirp_signal(
    duration=0.2,
    start_freq=500,
    end_freq=4000,
    sample_rate=44100,
):
    t = np.linspace(
        0,
        duration,
        int(duration * sample_rate),
        endpoint=False,
    )
    chirp_signal = np.sin(
        2
        * np.pi
        * np.interp(t, [0, duration], [start_freq, end_freq])
        * t
    )
    return chirp_signal


def extract_audio_from_video(video_file):
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_wav_file = os.path.join(
            tmpdirname,
            os.path.basename(video_file) + ".wav",
        )
        ffmpeg_command = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            video_file,
            "-vn",
            tmp_wav_file,
        ]
        result = subprocess.run(
            ffmpeg_command,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not os.path.exists(tmp_wav_file):
            raise RuntimeError(
                f"Could not extract audio from {video_file}. "
                "The video probably has no audio stream."
            )
        return read_wave(tmp_wav_file)


def has_audio_stream(video_file):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(video_file),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def ffprobe_values(video_file, select_stream, entries):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        select_stream,
        "-show_entries",
        entries,
        "-of",
        "csv=p=0",
        str(video_file),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def stream_start_time(video_file, select_stream):
    values = ffprobe_values(video_file, select_stream, "stream=start_time")
    try:
        return float(values[-1])
    except (IndexError, ValueError):
        return 0.0


def video_codec(video_file):
    values = ffprobe_values(video_file, "v:0", "stream=codec_name")
    return values[-1] if values else None


def remove_audio_offset(video_path):
    """Shift the camera audio stream to start together with the video stream."""
    video_start = stream_start_time(video_path, "v:0")
    audio_start = stream_start_time(video_path, "a:0")
    audio_offset = audio_start - video_start

    if abs(audio_offset) < AUDIO_OFFSET_TOLERANCE_S:
        print(f"Video: {video_path.parent.name}/{video_path.name}, no audio offset")
        return

    temporary_path = video_path.with_name(
        video_path.stem + "_audio_shifted" + video_path.suffix
    )
    ffmpeg_command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-itsoffset",
        f"{-audio_offset:.6f}",
        "-i",
        str(video_path),
        "-map",
        "0:v",
        "-map",
        "1:a:0",
        "-map_metadata",
        "0",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
    ]

    # FFmpeg WebM muxer accepts only VP8/VP9/AV1 video, so H.264 recordings
    # are written with the Matroska muxer while keeping the .webm extension.
    if video_codec(video_path) == "h264":
        ffmpeg_command += ["-f", "matroska"]

    ffmpeg_command.append(str(temporary_path))

    result = subprocess.run(
        ffmpeg_command,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not remove audio offset from {video_path}: "
            f"{result.stderr.strip()}"
        )

    temporary_path.replace(video_path)
    print(
        f"Video: {video_path.parent.name}/{video_path.name}, audio shifted by "
        f"{-audio_offset * 1000:.2f} ms"
    )


def video_duration(video_file):
    """Return the time from the first video frame to the end of the last frame."""
    pts_times = []
    last_frame_duration = None

    for line in ffprobe_values(video_file, "v:0", "packet=pts_time,duration_time"):
        parts = line.split(",")
        try:
            pts_times.append(float(parts[0]))
        except ValueError:
            continue
        try:
            last_frame_duration = float(parts[1])
        except (IndexError, ValueError):
            last_frame_duration = None

    if len(pts_times) < 2:
        return None

    pts_times.sort()
    if last_frame_duration is None:
        last_frame_duration = float(np.median(np.diff(pts_times)))

    return pts_times[-1] + last_frame_duration - pts_times[0]


def calculate_energy_with_stft(signal, fs, n_fft=2048):
    signal = signal - signal.mean()
    f, t, zxx = stft(signal, fs, window="hann", nperseg=n_fft)
    magnitude = np.abs(zxx)
    energy = np.sum(magnitude ** 2, axis=1)
    return f, t, magnitude, energy


def sync_spectrograms(ref, measured):
    if ref.shape == measured.shape:
        return 0

    ref = ref > np.max(ref) * 0.8
    ref = ref.astype(np.float32)
    ref = ref - ref.mean()
    corr = correlate2d(
        ref,
        np.log10(measured + 1e-10),
        "valid",
    ).squeeze()
    return len(corr) - np.argmax(corr)


def argmax_correlation(input_signal, sync_signal, fs, n_fft=1024):
    _, input_times, input_spectrum, _ = calculate_energy_with_stft(
        input_signal,
        fs,
        n_fft,
    )
    _, _, sync_spectrum, _ = calculate_energy_with_stft(
        sync_signal,
        fs,
        n_fft,
    )

    sync_index = sync_spectrograms(sync_spectrum, input_spectrum)
    if sync_index >= len(input_times):
        return None

    sync_time = input_times[sync_index]
    return int(sync_time * fs)


def find_delay_by_sync(
    video_file,
    audio_file,
    audio_channel,
    video_channel=0,
):
    audio_fs, audio_signal = read_wave(audio_file)
    audio_signal = audio_signal[audio_channel, :]
    sync_signal = generate_chirp_signal(sample_rate=audio_fs)
    audio_shift = argmax_correlation(
        audio_signal,
        sync_signal,
        audio_fs,
    )

    video_fs, video_signal = extract_audio_from_video(video_file)
    video_signal = video_signal[video_channel, :]

    if audio_fs != video_fs:
        sync_signal = generate_chirp_signal(sample_rate=video_fs)

    video_shift = argmax_correlation(
        video_signal,
        sync_signal,
        video_fs,
    )

    if None in [audio_shift, video_shift]:
        return None

    return audio_shift / audio_fs - video_shift / video_fs


def timestamp_delays():
    return {
        "dobot": DOBOT_CAMERA_DELAY_S,
        "usg_timestamps": USG_CAMERA_DELAY_S,
        "imu": IMU_CAMERA_DELAY_S,
        "psmove": PSMOVE_CAMERA_DELAY_S,
    }


def correct_csv(path, delay):
    """Add sync_timestamp to the CSV. Returns a problem description or None."""
    with path.open(newline="") as input_file:
        reader = csv.DictReader(input_file)
        fieldnames = list(reader.fieldnames or [])
        timestamp_column = next(
            (
                column
                for column in fieldnames
                if column.lower() == "timestamp"
            ),
            None,
        )

        if timestamp_column is None:
            print(f"Skipping {path}: no timestamp column")
            return f"{path.parent.name}/{path.name}: no timestamp column, CSV unchanged"

        timestamp_index = fieldnames.index(timestamp_column) + 1
        if "sync_timestamp" not in fieldnames:
            fieldnames.insert(timestamp_index, "sync_timestamp")

        rows = list(reader)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    try:
        with temporary_path.open("w", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=fieldnames)
            writer.writeheader()

            for row in rows:
                raw_timestamp = float(row[timestamp_column])
                row["sync_timestamp"] = f"{raw_timestamp - delay:.6f}"
                writer.writerow(row)

        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)

    print(f"CSV: {path}, delay={delay * 1000:.2f} ms")
    return None


def report(problems, message):
    print(message)
    problems.append(message)


def trim_audio_to_video(audio_path, video_path, audio_channel):
    """Cut the WAV so it starts and ends together with the video. Returns problems."""
    problems = []
    delay = find_delay_by_sync(
        str(video_path),
        str(audio_path),
        audio_channel,
        VIDEO_AUDIO_CHANNEL,
    )

    if delay is None:
        report(problems, f"Audio unchanged: could not find chirp in {audio_path.name}")
        return problems

    duration = video_duration(video_path)
    if duration is None:
        report(problems, f"Audio unchanged: could not read duration of {video_path.name}")
        return problems

    sample_rate, samples = wavfile.read(audio_path)

    # WAV time = video time + delay
    start_sample = max(0, int(round(delay * sample_rate)))
    end_sample = min(
        len(samples),
        int(round((duration + delay) * sample_rate)),
    )

    if start_sample >= end_sample:
        report(
            problems,
            f"Audio unchanged: {audio_path.name} does not overlap the video, "
            f"delay={delay:.6f} s"
        )
        return problems

    if delay < 0:
        report(
            problems,
            f"Audio: {audio_path.name} starts {-delay:.6f} s after the "
            "video, start unchanged"
        )
    if end_sample == len(samples) and (duration + delay) * sample_rate > len(samples):
        report(
            problems,
            f"Audio: {audio_path.name} ends before the video, end unchanged"
        )

    if start_sample == 0 and end_sample == len(samples):
        print(f"Audio unchanged: {audio_path.name}, delay={delay:.6f} s")
        return problems

    temporary_path = audio_path.with_name(
        audio_path.stem + "_sync_tmp" + audio_path.suffix
    )
    try:
        wavfile.write(
            temporary_path,
            sample_rate,
            samples[start_sample:end_sample],
        )
        temporary_path.replace(audio_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    print(
        f"Audio: {audio_path.name}, removed "
        f"{start_sample / sample_rate:.6f} s from start and "
        f"{(len(samples) - end_sample) / sample_rate:.6f} s from end, "
        f"duration {(end_sample - start_sample) / sample_rate:.6f} s"
    )
    return problems


def process_recording(name, videos, root_dir, audio_dir, delays, audio_channel):
    """Synchronize one recording. Returns descriptions of unchanged or partly changed files."""
    print(f"\nRecording: {name}")
    problems = []

    for folder_name, delay in delays.items():
        source = root_dir / folder_name / f"{name}.csv"
        if not source.is_file():
            continue

        problem = correct_csv(source, delay)
        if problem:
            problems.append(problem)

    # videos are ordered cam1, cam2, so cam1 is the reference when it has audio
    videos_with_audio = [
        video for video in videos if has_audio_stream(video)
    ]
    for video in videos_with_audio:
        remove_audio_offset(video)

    video_with_audio = videos_with_audio[0] if videos_with_audio else None

    audio_path = audio_dir / f"{name}.wav"
    if not audio_path.is_file():
        report(problems, f"Audio unchanged: no raw audio for {name}")
        return problems

    if video_with_audio is None:
        report(
            problems,
            f"Audio unchanged: no embedded camera audio for "
            f"{audio_path.name}"
        )
        return problems

    problems.extend(trim_audio_to_video(audio_path, video_with_audio, audio_channel))
    return problems


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize sensor data timestamps and Raspberry Pi MEMS audio "
            "with camera recordings."
        )
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=Path.cwd(),
        help=(
            "Directory containing video_cam1/, video_cam2/, audio_raw/ and "
            "sensor data folders (default: current directory)."
        ),
    )
    parser.add_argument(
        "--audio-channel",
        type=int,
        required=True,
        help=(
            "Audio channel to use for synchronization"
        ),
    )
    return parser.parse_args()


def main():
    delays = timestamp_delays()
    recordings = {}
    args = parse_args()

    root_dir = args.root_dir
    video_dirs = [root_dir / folder for folder in CAMERA_VIDEO_DIRS.values()]
    audio_dir = root_dir / AUDIO_RAW_DIR

    if not any(video_dir.is_dir() for video_dir in video_dirs):
        raise FileNotFoundError(
            "Video directories do not exist: "
            + ", ".join(str(video_dir) for video_dir in video_dirs)
        )

    for video_dir in video_dirs:
        if not video_dir.is_dir():
            continue

        for video_path in sorted(video_dir.iterdir()):
            if not video_path.is_file():
                continue

            recordings.setdefault(video_path.stem, []).append(video_path)

    failed_recordings = []
    for name in sorted(recordings):
        try:
            problems = process_recording(name, recordings[name], root_dir, audio_dir, delays, args.audio_channel)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            print(f"Error processing {name}, skipping: {error}")
            problems = [f"Error, recording skipped: {error}"]
        if problems:
            failed_recordings.append((name, problems))

    print("\nFinished.")
    if failed_recordings:
        print(f"\nRecordings with problems: {len(failed_recordings)}/{len(recordings)}")
        for name, problems in failed_recordings:
            print(f"  {name}")
            for problem in problems:
                print(f"    - {problem}")


if __name__ == "__main__":
    main()

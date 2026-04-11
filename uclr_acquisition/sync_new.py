from email.mime import audio
import json
import numpy as np
import subprocess
import tempfile
import os
from vnav_acquisition.clean import highpass, read_wave
from vnav_acquisition.sound import generate_chirp_signal
import argparse
import glob
from collections import defaultdict
from scipy.signal import stft, correlate2d, firwin, filtfilt, fftconvolve, windows
import matplotlib.pyplot as plt
import pandas as pd

def debug_plot_sync(ref, input_spec, idx_sync):
    plt.figure(figsize=(12, 6))
    plt.subplot(1, 2, 1)
    plt.title("Chirp spectrum")
    plt.imshow(np.log10(ref + 1e-10), aspect='auto', origin='lower')
    plt.subplot(1, 2, 2)
    plt.title("Input sound spectrum")
    plt.imshow(np.log10(input_spec + 1e-10), aspect='auto', origin='lower')
    plt.axvline(x=idx_sync, color='r', linestyle='--', label='Correlation')
    plt.legend()
    plt.tight_layout()
    plt.show()

def extract_audio_from_video(video_file):
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_wav_file = os.path.join(tmpdirname, os.path.basename(video_file) + ".wav")
        ffmpeg_command = ['ffmpeg', '-loglevel', 'error', '-i', video_file, tmp_wav_file]

        try:
            subprocess.run(ffmpeg_command)
            fs, x = read_wave(tmp_wav_file)
            os.remove(tmp_wav_file)
            return fs, x
        except subprocess.CalledProcessError as e:
            print(f'Error while executing FFmpeg: {e}')
            raise e
        
def ffprobe_value(filename, select_stream):

    command = [
        "ffprobe", "-v", "error",
        "-select_streams", select_stream,
        "-show_entries", "stream=start_time",
        "-of", "csv=p=0",
        filename
    ]
    p = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = p.stdout.strip()
    if not out:
        return None
    
    try:
        val = float([l for l in out.splitlines() if l.strip()][-1])
        return val
    except ValueError:
        return None

def get_stream_start_times(filename):
    v_start = ffprobe_value(filename, "v:0")
    a_start = ffprobe_value(filename, "a:0")
    return (0.0 if v_start is None else v_start,
            0.0 if a_start is None else a_start)
        
def remove_audio_offset(video_path):
    video_start, audio_start = get_stream_start_times(video_path)
    audio_offset = audio_start - video_start
    print(f'Audio offset in {video_path}: {audio_offset:.6f} seconds')

    if abs(audio_offset) < 0.001:
        print('No audio offset detected')
        return

    tmp_path = video_path.replace(".mp4", "_audio_shifted.mp4")
    ffmpeg_command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-itsoffset", f'{-audio_offset:.6f}',
        "-i", video_path,
        "-map", "0:v", "-map", "1:a:0",
        "-map", "0:s?",
        "-map_metadata", "0",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        tmp_path
    ]

    subprocess.run(ffmpeg_command)
    os.replace(tmp_path, video_path)
        
def cut_video(video_path, cut_seconds):
    if abs(cut_seconds) < 0.001:
        print('No cutting needed')
        return
    
    print(f'Cutting video {video_path} at {cut_seconds:.6f} seconds')
    tmp_path = video_path.replace(".mp4", "_shifted.mp4")
    ffmpeg_command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-ss", f'{cut_seconds:.6f}',
        "-map", "0",
        "-c:v", "libx264",
        tmp_path
    ]

    subprocess.run(ffmpeg_command)
    os.replace(tmp_path, video_path)

def get_audio_duration(audio_file, audio_channel):
    audio_fs, audio_signal = read_wave(audio_file)
    audio_signal = audio_signal[audio_channel, :]
    audio_duration = len(audio_signal) / audio_fs
    return audio_duration

def trim_video_end(video_path, target_duration):
    
    print(f'Trimming video {video_path} to {target_duration:.6f} seconds')

    tmp_path = video_path.replace(".mp4", "_trimmed.mp4")
    ffmpeg_command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-t", f'{target_duration:.6f}',
        "-map", "0",
        "-c:v", "libx264",
        tmp_path
    ]

    subprocess.run(ffmpeg_command)
    os.replace(tmp_path, video_path)

def calculate_energy_with_stft(signal: np.ndarray, fs: int, n_fft: int = 2048, show=False):
    signal = signal - signal.mean()
    f, t, Zxx = stft(signal, fs, window='hann', nperseg=n_fft)
    Zxx_magnitude = np.abs(Zxx)

    # Signal is squared to calculate energy
    energy = np.sum(Zxx_magnitude ** 2, axis=1)

    return f, t, Zxx_magnitude, energy

def sync_spectrograms(ref, measured):
    if ref.shape == measured.shape:
        return 0
    ref = ref > np.max(ref) * 0.8
    ref = ref.astype(np.float32)
    ref = ref - ref.mean()
    corr = correlate2d(ref, np.log10(measured + 1e-10), 'valid').squeeze()
    idx = len(corr) - np.argmax(corr)
    
    return idx

def argmax_correlation(input_signal, sync_signal, fs, debug_plots, n_fft=1024):
    
    f_input, t_input, spec_input, energy_input = calculate_energy_with_stft(input_signal, fs, n_fft)
    f_sync, t_sync, spec_sync, energy_sync = calculate_energy_with_stft(sync_signal, fs, n_fft)

    idx_sync = sync_spectrograms(spec_sync, spec_input)

    if debug_plots:
        debug_plot_sync(spec_sync, spec_input, idx_sync)

    if idx_sync >= len(t_input):
        return None
    
    sync_signal_time = t_input[idx_sync]

    sample_index = int(sync_signal_time * fs)
    return sample_index


def find_delay_by_sync(video_file, audio_file, audio_channel, debug_plots, video_channel=0) -> [float, int]:
    """
    Finds a delay between audio and video recordings based on the position of synchronization sound.
    :param video_file: Path of video file.
    :param audio_file: Path of audio file.
    :param audio_channel: Which channel to look for sync wave in audio file.
    :param video_channel: Which channel to look for sync wave in vieo file.
    :return: Audio file delay in seconds, in respect to audio from video file.
    """
    audio_fs, audio_signal = read_wave(audio_file)
    audio_signal = audio_signal[audio_channel, :]
    sync_signal = generate_chirp_signal(sample_rate=audio_fs)
    audio_shift = argmax_correlation(audio_signal, sync_signal, audio_fs, debug_plots)

    video_fs, video_signal = extract_audio_from_video(video_file)
    video_signal = video_signal[video_channel, :]
    if audio_fs != video_fs:
        sync_signal = generate_chirp_signal(sample_rate=video_fs)
    video_shift = argmax_correlation(video_signal, sync_signal, video_fs, debug_plots)

    if None in [audio_shift, video_shift]:
        return video_shift, audio_shift
    else:
        audio_delay = audio_shift/audio_fs - video_shift/video_fs
        return audio_delay, audio_fs


def main():
    parser = argparse.ArgumentParser(description="Cut video files to start at the same time as audio files.")
    parser.add_argument("--audio-path", type=str, required=True,
                        help="Path to audio files")
    parser.add_argument("--first-video-path", type=str, required=True,
                        help="Path to video (mp4) files")
    parser.add_argument("--second-video-path", type=str, required=True,
                        help="Path to video (mp4) files")
    parser.add_argument("--audio-channel", type=int, default=-1,
                        help="Index of channel in WAV audio file to use for sync (e.g. 0=left, 1=right, -1=last). Default: -1")
    parser.add_argument("--debug-plots", action="store_true", help="Show debug plots for synchronization")
    args = parser.parse_args()

    audio_folder_path = args.audio_path
    video1_folder_path = args.first_video_path
    video2_folder_path = args.second_video_path
    debug_plots = args.debug_plots
    audio_channel = args.audio_channel

    files_to_process = [
        os.path.splitext(f)[0] 
        for f in os.listdir(audio_folder_path)
        if f.endswith('.wav')]
    
    files_to_process = sorted(files_to_process)
    wrong_chirp_detection_files = []
    for filename in files_to_process:
        audio_file = os.path.join(audio_folder_path, f'{filename}.wav')
        video1_file = os.path.join(video1_folder_path, f'{filename}.mp4')
        video2_file = os.path.join(video2_folder_path, f'{filename}.mp4')
        if not os.path.exists(video1_file) or not os.path.exists(video2_file) or not os.path.exists(audio_file):
            print(f"Missing video file: {video1_file} or {video2_file} or audio file: {audio_file}")
            continue

        remove_audio_offset(video1_file)
        remove_audio_offset(video2_file)

        audio_video1_delay, audio_fs1 = find_delay_by_sync(video1_file, audio_file, audio_channel, debug_plots)
        audio_video2_delay, audio_fs2 = find_delay_by_sync(video2_file, audio_file, audio_channel, debug_plots)
        if audio_video1_delay > 0 or audio_video2_delay > 0:
            wrong_chirp_detection_files.append(filename)
            continue
        else:
            cut_video(video1_file, -audio_video1_delay)
            cut_video(video2_file, -audio_video2_delay)

        audio_duration = get_audio_duration(audio_file, audio_channel)
        trim_video_end(video1_file, audio_duration)
        trim_video_end(video2_file, audio_duration)

    print(f'Number of files with wrong chirp detection: {len(wrong_chirp_detection_files)}')
    print(f'Wrong chirp detection files: {wrong_chirp_detection_files}')


if __name__ == "__main__":
    main()
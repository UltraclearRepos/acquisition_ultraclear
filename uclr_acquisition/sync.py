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


def modify_annotation_file(annotation_file, audio_file, audio_delay, audio_fs):
    with open(annotation_file) as f:
        annotation_set = json.load(f)

    if "audio_annotations" in annotation_set:
        return
    
    video_annotations = annotation_set["video_annotations"]
    if type(video_annotations) is list:
        print(f'Annotation file format no longer supported: {annotation_file}')
    elif type(video_annotations) is dict:
        audio_annotations = defaultdict(dict)
        for event, video_annotation in video_annotations.items():
            audio_annotations[event]["time"] = video_annotation["time"] + audio_delay
            audio_annotations[event]["sample"] = int(audio_annotations[event]["time"] * audio_fs)
    else:
        print(f'Annotation file has unknown format! : {annotation_file}')

    annotation_set["audio_file"] = os.path.basename(audio_file)
    annotation_set["audio_annotations"] = audio_annotations

    with open(annotation_file, 'w') as f:
        json.dump(annotation_set, f, indent=4)

def modify_needle_position_file(needle_position_file, audio_delay):
    df = pd.read_csv(needle_position_file)
    df["Audio time (s)"] = df["Time (s)"] + audio_delay
    df.to_csv(needle_position_file, index=False)

def add_audio_annotations(video_file, audio_file, annotation_file, needle_position_file, audio_channel, debug_plots):

    audio_delay, audio_fs = find_delay_by_sync(video_file, audio_file, audio_channel, debug_plots)

    print(audio_delay)

    if audio_delay is None:
        return f"Video file sound corrupted: {video_file}"
    if audio_fs is None:
        return f"Audio file sound corrupted: {audio_file}"

    if annotation_file is not None:
        modify_annotation_file(annotation_file, audio_file, audio_delay, audio_fs)

    if needle_position_file is not None:
        modify_needle_position_file(needle_position_file, audio_delay)


def main():
    parser = argparse.ArgumentParser(description="Writes audio annotation based on synchronization between audio, "
                                                 "video and video annotations.")
    parser.add_argument("--audio-path", type=str, required=True,
                        help="Path to audio files")
    parser.add_argument("--audio-suffix", type=str, default="",
                        help='Suffix of audio file, compared to video and annotation files (default: "")')
    parser.add_argument("--video-path", type=str, default="", required=False,
                        help="Path to video (webm, mp4) files (default: same as audio files)")
    parser.add_argument("--annotation-path", type=str, default="", required=False,
                        help="Path to annotations files (default: same as audio files)")
    parser.add_argument("--needle-position-path", type=str, help="Path to needle position files" \
                         " If not provided needle position files will not be processed")
    parser.add_argument("--audio-channel", type=int, default=-1,
                        help="Index of channel in WAV audio file to use for sync (e.g. 0=left, 1=right, -1=last). Default: -1")
    parser.add_argument("--debug-plots", action="store_true", help="Show debug plots for synchronization")
    args = parser.parse_args()

    if not args.video_path:
        args.video_path = args.audio_path
    if not args.annotation_path:
        args.annotation_path = args.audio_path
    

    audio_files = {
        os.path.splitext(os.path.basename(f))[0].replace(args.audio_suffix, ""): os.path.join(args.audio_path, f)
        for f in os.listdir(args.audio_path)
        if os.path.isfile(os.path.join(args.audio_path, f)) and f.endswith('.wav')
    }
    
    video_files = {
        os.path.splitext(os.path.basename(f))[0]: os.path.join(args.video_path, f)
        for f in os.listdir(args.video_path)
        if os.path.isfile(os.path.join(args.video_path, f)) and f.endswith(('.webm', '.mp4'))
    }
    
    annotation_files = {
        os.path.splitext(os.path.basename(f))[0]: os.path.join(args.annotation_path, f)
        for f in os.listdir(args.annotation_path)
        if os.path.isfile(os.path.join(args.annotation_path, f)) and f.endswith('.json')
    }
    
    needle_position_files = {}
    if args.needle_position_path:
        needle_position_files = {
            os.path.splitext(os.path.basename(f))[0]: os.path.join(args.needle_position_path, f)
            for f in os.listdir(args.needle_position_path)
            if os.path.isfile(os.path.join(args.needle_position_path, f)) and f.endswith('.csv')
        }
    
    debug_plots = args.debug_plots
    audio_channel = args.audio_channel

    files_to_process = set(annotation_files.keys() | needle_position_files.keys())
    files_to_process = sorted(files_to_process)
    skipped = []
    for filename in files_to_process:
        audio_present = filename in audio_files
        video_present = filename in video_files
        if audio_present and video_present:
            print(f"Processing {filename}")
            result = add_audio_annotations(
                video_files[filename], 
                audio_files[filename], 
                annotation_files[filename] if filename in annotation_files else None,
                needle_position_files[filename] if filename in needle_position_files else None,
                audio_channel, 
                debug_plots
            )
            if result:
                print(result)
                skipped.append(result)
        else:
            if not audio_present:
                result = f"Missing audio for: {filename}"
                print(result)
                skipped.append(result)
            if not video_present:
                result = f"Missing video for: {filename}"
                print(result)
                skipped.append(result)
    if skipped:
        print(f"Skipped {len(skipped)} files with missing data file (video or annotations)")
        with open(os.path.join(args.annotation_path, "log.txt"), 'w') as fp:
            fp.writelines([line + "\n" for line in skipped])


if __name__ == "__main__":
    main()
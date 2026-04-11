import argparse
import os
import subprocess
from .sync import extract_audio_from_video, argmax_correlation
from vnav_acquisition.sound import generate_chirp_signal
import time

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

def cut_video(video_path, cut_seconds):
    print(f'Cutting video {video_path} at {cut_seconds:.6f} seconds')
    tmp_path = video_path.replace(".mp4", "_shifted.mp4")
    ffmpeg_command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-ss", f'{cut_seconds:.6f}',
        "-map", "0",
        "-c:v", "libx264",
        "-movflags", "+faststart",
        "-map_metadata", "0",
        tmp_path
    ]

    subprocess.run(ffmpeg_command)
    os.replace(tmp_path, video_path)

def remove_audio_offset(video_path):
    video_start, audio_start = get_stream_start_times(video_path)
    audio_offset = audio_start - video_start

    if abs(audio_offset) > 0:
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

def parse_args():
    parser = argparse.ArgumentParser(
        description="Tool for synchrozing video to make them start at same time. Tool is cutting videos and override!" \
                    " Tool will synchronize videos with same filename in both folders." \
                    " Video will be cut to start 0.2 seconds before chirp sound. If it is to short, it will be cut to the start of chirp sound."
    )
    parser.add_argument("--first-video-folder", required=True, type=str, help="Path to folder with first video(s).")
    parser.add_argument("--second-video-folder", required=True, type=str, help="Path to folder with second video(s).")
    parser.add_argument("--debug-plots", action='store_true', help="If set, debug plots will be shown.")
    return parser.parse_args()

def main():
    args = parse_args()

    first_video_folder = args.first_video_folder
    second_video_folder = args.second_video_folder
    debug_plots = args.debug_plots

    video_filenames = [f for f in os.listdir(first_video_folder) if f.endswith(".mp4")]

    for video_filename in video_filenames:
        first_video_path = os.path.join(first_video_folder, video_filename)
        second_video_path = os.path.join(second_video_folder, video_filename)

        if not os.path.exists(first_video_path) or not os.path.exists(second_video_path):
            print(f"Missing video file(s) for synchronization: {first_video_path}, {second_video_path}")
            continue

        remove_audio_offset(first_video_path)
        remove_audio_offset(second_video_path)

        fs1, signal1 = extract_audio_from_video(first_video_path)
        signal1 = signal1[0, :]
        sync_signal = generate_chirp_signal(sample_rate=fs1)
        video1_shift = argmax_correlation(signal1, sync_signal, fs1, debug_plots=debug_plots)

        fs2, signal2 = extract_audio_from_video(second_video_path)
        signal2 = signal2[0, :]
        if fs2 != fs1:
            sync_signal = generate_chirp_signal(sample_rate=fs2)
        video2_shift = argmax_correlation(signal2, sync_signal, fs2, debug_plots=debug_plots)

        video1_shift_seconds = (video1_shift / fs1)
        video2_shift_seconds = (video2_shift / fs2)

        if video1_shift_seconds - 0.2 > 0 and video2_shift_seconds - 0.2 > 0:
            cut1 = video1_shift_seconds - 0.2
            cut2 = video2_shift_seconds - 0.2
        else:
            cut1 = video1_shift_seconds
            cut2 = video2_shift_seconds

        cut_video(first_video_path, cut1)
        cut_video(second_video_path, cut2)

if __name__ == "__main__":
    main()
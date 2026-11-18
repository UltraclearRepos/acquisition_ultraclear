import argparse
from functools import lru_cache
import json
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile

import cv2
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

from ..config import AUDIO_RAW_DIR, CAMERA_VIDEO_DIRS
from ..synchronize import read_wave


ANNOTATIONS_FOLDER_NAME = "annotations"
POSITIONS_FOLDER_NAME = "labelled_positions"

# OpenCV reports different arrow codes on Windows, GTK and Qt.
FRAME_STEPS = {
    0x250000: -1, 0x270000: 1,
    0xFF51: -1, 0xFF53: 1,
    0x01000012: -1, 0x01000014: 1,
}


@lru_cache(maxsize=2)
def build_spectrogram(audio_path, channel, width):

    AUDACITY_COLORS = LinearSegmentedColormap.from_list(
    "audacity", ["black", "#001b70", "#d020a0", "#ff7a30", "white"]
    )

    sample_rate, audio = read_wave(audio_path)
    samples = audio[channel].astype(np.float32)
    duration = len(samples) / sample_rate

    height = 140
    dpi = 128
    figure = Figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor="#181818")
    canvas = FigureCanvasAgg(figure)
    axis = figure.add_axes([0, 0, 1, 1], facecolor="#181818")
    nfft = 512
    with np.errstate(divide="ignore"):
        axis.specgram(
            samples, NFFT=nfft, Fs=sample_rate, noverlap=384, pad_to=1024,
            window=np.hanning(nfft), cmap=AUDACITY_COLORS, scale="dB",
            scale_by_freq=False, xextent=(0, duration) if duration else None,
            vmin=-100, vmax=-20,
        )
    axis.set_yscale("function", functions=(
        lambda hz: 2595 * np.log10(1 + hz / 700),
        lambda mel: 700 * (10 ** (mel / 2595) - 1),
    ))
    axis.set_ylim(0, min(24_000, sample_rate / 2))
    axis.set_axis_off()

    canvas.draw()
    image = cv2.cvtColor(np.asarray(canvas.buffer_rgba()), cv2.COLOR_RGBA2BGR)
    return image, duration, sample_rate


def save_annotation(path, number, previous_data, video_update, audio_update):
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    video_annotation = data["video_annotations"].get(number)
    audio_annotation = (data.get("audio_annotations") or {}).get(number)
    if (video_annotation != previous_data["video_annotations"][number]
            or audio_annotation != (previous_data.get("audio_annotations") or {}).get(number)):
        raise ValueError("The annotation changed on disk. Reopen the viewer before editing.")

    video_annotation.update(video_update)
    if audio_update is not None:
        audio_annotation.update(audio_update)

    file = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
    temporary_path = Path(file.name)
    try:
        with file:
            json.dump(data, file, indent=4)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return data


def copy_to_fix(video_path, second_video_folder, audio_folder):
    sources = [
        (video_path, "tofix_video_cam1"),
        (Path(second_video_folder) / video_path.name, "tofix_video_cam2"),
        (Path(audio_folder) / f"{video_path.stem}.wav", "tofix_audio_raw"),
    ]
    for source, folder_name in sources:
        # Recordings can be made with one camera or without the MEMS WAV
        if not source.is_file():
            print(f"Skipping {source}: file not found.")
            continue
        destination = source.parent.parent / folder_name
        destination.mkdir(exist_ok=True)
        shutil.copy2(source, destination / source.name)
    print(f"Copied {video_path.stem} to tofix folders.")


def parse_args():
    parser = argparse.ArgumentParser(description=(
        "Browse annotated video frames and needle positions. Videos are read from video_cam1/, "
        "WAV files from audio_raw/, annotations from annotations/ and positions from "
        "labelled_positions/."
    ))
    parser.add_argument("--root-dir", type=Path, default=Path.cwd(),
                        help="Directory containing video_cam1/, video_cam2/, audio_raw/, annotations/ "
                             "and labelled_positions/ folders (default: current directory).")
    parser.add_argument("--audio-channel", type=int, required=True, help="WAV channel for the spectrogram")
    return parser.parse_args()


def main():
    args = parse_args()

    root_dir = args.root_dir
    video_folder = root_dir / CAMERA_VIDEO_DIRS["cam1"]
    second_video_folder = root_dir / CAMERA_VIDEO_DIRS["cam2"]
    audio_folder = root_dir / AUDIO_RAW_DIR
    annotations_folder = root_dir / ANNOTATIONS_FOLDER_NAME
    positions_folder = root_dir / POSITIONS_FOLDER_NAME

    items = []
    recordings = {}
    video_paths = sorted(
        path for path in video_folder.glob("*")
        if path.is_file() and path.suffix.lower() in (".mp4", ".webm")
    )
    for video_path in video_paths:
        annotation_path = annotations_folder / f"{video_path.stem}.json"
        positions_path = positions_folder / f"{video_path.stem}.csv"
        if not annotation_path.is_file() or not positions_path.is_file():
            print(f"Skipping {video_path.name}: missing {annotation_path} or {positions_path}")
            continue
        with annotation_path.open(encoding="utf-8") as file:
            data = json.load(file)
        positions = pd.read_csv(positions_path).set_index("Frame")
        recordings[video_path] = (annotation_path, data, positions)
        items.extend((video_path, number) for number in sorted(data["video_annotations"], key=int))

    if not items:
        print("No annotations to display.")
        return

    index = 0
    playing = False
    preview_frame = None
    cv2.namedWindow("Annotations", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Annotations", 1600, 1000)

    while True:
        video_path, number = items[index]
        annotation_path, data, positions = recordings[video_path]
        video_annotations = data["video_annotations"]
        audio_annotations = data.get("audio_annotations") or {}
        annotation = video_annotations[number]
        audio_annotation = audio_annotations.get(number)
        audio_time = (audio_annotation or {}).get("time")
        saved_frame = int(annotation["frame"])
        frame_number = saved_frame if preview_frame is None else preview_frame
        cap = cv2.VideoCapture(str(video_path))
        # CAP_PROP_FRAME_COUNT is unreliable for browser WebM recordings, while
        # track_position stores every frame read from the video.
        frame_count = int(positions.index.max()) or int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        # track_position numbers frames from 1; OpenCV seeks from 0.
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number - 1)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            print(f"Could not read frame {frame_number} from {video_path.name}.")
            if preview_frame is not None:
                preview_frame = None
                continue
            break

        frame_time = annotation["time"]
        position = positions.loc[frame_number] if frame_number in positions.index else None
        if preview_frame is not None:
            tracked_time = position.get("Time (s)") if position is not None else None
            if pd.notna(tracked_time):
                frame_time = float(tracked_time)
            elif fps > 0:
                frame_time += (frame_number - saved_frame) / fps
            else:
                print(f"No timestamp for frame {frame_number} in {video_path.name}.")
                preview_frame = None
                continue

        marker_time = annotation["time"] if audio_time is None else audio_time
        preview_audio_time = frame_time
        frame = cv2.copyMakeBorder(
            frame, 160, 0, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0)
        )
        audio_path = audio_folder / f"{video_path.stem}.wav"
        sample_rate = None
        if audio_path.is_file():
            chart, duration, sample_rate = build_spectrogram(
                audio_path, args.audio_channel, frame.shape[1]
            )
            time_source = "video time" if audio_time is None else "audio time"
            marker_label = f" | WAV marker: {marker_time:.3f} s ({time_source})"
            if not 0 <= marker_time <= duration:
                marker_label += " - outside WAV"

            marker_times = {event: entry["time"] for event, entry in video_annotations.items()}
            marker_times.update(
                (event, entry["time"])
                for event, entry in audio_annotations.items()
                if entry.get("time") is not None
            )
            yellow = (0, 215, 255)
            markers = [(time, yellow, 1) for event, time in marker_times.items() if event != number]
            markers.append((marker_time, (60, 235, 90), 3))
            if preview_frame is not None:
                markers.append((preview_audio_time, (255, 145, 45), 1))
                marker_label += f" | Preview on WAV: {preview_audio_time:.3f} s"
            chart = chart.copy()
            chart_height, chart_width = chart.shape[:2]
            for time, color, thickness in markers:
                if duration > 0 and 0 <= time <= duration:
                    x = int(time / duration * (chart_width - 1))
                    cv2.line(chart, (x, 0), (x, chart_height - 1), color, thickness)
            frame = cv2.vconcat([frame, chart])
        else:
            marker_label = " | WAV unavailable"
        position_label = "Needle position unavailable"
        if position is not None:
            position_label = (f"Needle [cm]: X={position['Object_X_cm']:.2f}  "
                              f"Y={position['Object_Y_cm']:.2f}  Z={position['Object_Z_cm']:.2f}")
        lines = [
            video_path.name,
            f"Annotation: {number} | Frame: {frame_number} | Time: {frame_time:.3f} s{marker_label}",
            position_label,
            f"{index + 1}/{len(items)} | {'PLAY' if playing else 'PAUSE'} | "
            "Space: play/pause | A: previous | D: next | F: copy to fix | Esc: exit",
            "Left/Right: step one frame (blue) | Enter: save annotation (green)",
        ]
        for line_index, text in enumerate(lines):
            cv2.putText(
                frame, text, (10, 25 + line_index * 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA
            )
        cv2.imshow("Annotations", frame)

        key = cv2.waitKeyEx(1000 if playing else 0)
        if key == 27:
            break
        elif key == ord(" "):
            playing = not playing
            if playing:
                preview_frame = None
        elif key == ord("a"):
            index = max(0, index - 1)
            playing = False
            preview_frame = None
        elif key == ord("d"):
            index = min(len(items) - 1, index + 1)
            playing = False
            preview_frame = None
        elif key in FRAME_STEPS:
            playing = False
            target_frame = min(frame_count, max(1, frame_number + FRAME_STEPS[key]))
            preview_frame = None if target_frame == saved_frame else target_frame
        elif key in (10, 13, 0x01000004, 0x01000005) and preview_frame is not None:
            audio_update = None
            if audio_annotation is not None:
                if sample_rate is None or not 0 <= preview_audio_time < duration:
                    print("Cannot save: the new audio marker must fall within the WAV file.")
                    continue
                audio_update = {
                    "sample": int(preview_audio_time * sample_rate),
                    "time": preview_audio_time,
                }
            try:
                data = save_annotation(
                    annotation_path, number, data,
                    {"frame": frame_number, "time": frame_time}, audio_update,
                )
            except (OSError, ValueError) as error:
                print(f"Could not save annotation {number}: {error}")
                continue
            recordings[video_path] = (annotation_path, data, positions)
            preview_frame = None
            print(f"Saved annotation {number} in {annotation_path.name} at frame {frame_number}.")
        elif key == ord("f"):
            copy_to_fix(video_path, second_video_folder, audio_folder)
        elif key == -1 and playing:
            if index < len(items) - 1:
                index += 1
                preview_frame = None
            else:
                playing = False

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

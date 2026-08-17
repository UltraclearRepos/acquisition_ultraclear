import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

import cv2
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile

from .audio_player import AudioPlayer


WINDOW_NAME = "Video Annotation"
VIDEO_FOLDER_NAME = "videos"
DEFAULT_AUDIO_FOLDER_NAME = "micro_data"
ANNOTATIONS_FOLDER_NAME = "annotations"
SETUP_FILENAME = "setup.json"
DEFAULT_AUDIO_CHANNEL = 0

MAX_WINDOW_WIDTH = 1600
MAX_WINDOW_HEIGHT = 1200
WINDOW_HORIZONTAL_MARGIN = 40
WINDOW_VERTICAL_MARGIN = 80
WINDOW_CHROME_HEIGHT_ALLOWANCE = 100
MAX_CONTENT_HEIGHT_SCREEN_FRACTION = 0.75
CONTROL_BAR_HEIGHT = 48
DEFAULT_PLOT_HEIGHT = 140
MIN_PLOT_HEIGHT = 48

ctrl_pressed = False
event_key = None
show_mode = 1  # 0=waveform, 1=spectrogram
zoom_level = 1.0
zoom_center = None
last_frame = None
display_video_size = None
source_video_size = None
control_regions = {}
keyboard = None


def _on_press(key):
    global ctrl_pressed, event_key
    try:
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            ctrl_pressed = True
        elif hasattr(key, "char") and key.char is not None:
            event_key = key.char
        elif hasattr(key, "vk"):
            event_key = chr(key.vk)
    except Exception as exc:
        print(f"Error in key press: {exc}")


def _on_release(key):
    global ctrl_pressed, event_key
    try:
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            ctrl_pressed = False
        else:
            event_key = None
    except Exception as exc:
        print(f"Error in key release: {exc}")


def read_wave(path):
    sample_rate, signal = wavfile.read(path)
    signal = signal.T
    if signal.dtype == np.int32:
        signal = signal / float(2**31 - 1)
    elif signal.dtype == np.int16:
        signal = signal / float(2**15 - 1)
    if signal.ndim == 1:
        signal = signal[None, :]
    return sample_rate, signal


def get_screen_size(default=(1280, 720)):
    try:
        if os.name == "nt":
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()

            class Rect(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            rect = Rect()
            if ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0
            ):
                return rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        screen_size = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return screen_size
    except Exception:
        return default


def calculate_display_layout(video_width, video_height):
    screen_width, screen_height = get_screen_size()
    available_width = max(1, screen_width - 2 * WINDOW_HORIZONTAL_MARGIN)
    available_height = max(1, screen_height - 2 * WINDOW_VERTICAL_MARGIN)
    max_content_width = min(MAX_WINDOW_WIDTH, available_width)
    max_window_height = min(MAX_WINDOW_HEIGHT, available_height)
    max_content_height = min(
        max(1, max_window_height - WINDOW_CHROME_HEIGHT_ALLOWANCE),
        max(1, int(available_height * MAX_CONTENT_HEIGHT_SCREEN_FRACTION)),
    )

    min_plot_height = min(MIN_PLOT_HEIGHT, max(1, max_content_height // 4))
    plot_height = min(
        DEFAULT_PLOT_HEIGHT,
        max(min_plot_height, int(max_content_height * 0.12)),
    )
    available_video_height = max(
        1, max_content_height - plot_height - CONTROL_BAR_HEIGHT
    )
    aspect_ratio = video_width / max(1, video_height)
    target_width = min(video_width, max_content_width)
    target_height = int(round(target_width / aspect_ratio))

    if target_height > available_video_height:
        target_height = available_video_height
        target_width = int(round(target_height * aspect_ratio))

    return {
        "video_width": max(1, int(target_width)),
        "video_height": max(1, int(target_height)),
        "plot_width": max(1, int(target_width)),
        "plot_height": plot_height,
        "control_height": CONTROL_BAR_HEIGHT,
    }


def build_waveform_image(
    audio_signal,
    sample_rate,
    width,
    height,
    audio_channel,
    background=(24, 24, 24),
    foreground=(230, 230, 230),
):
    image = np.full((height, width, 3), background, dtype=np.uint8)
    if audio_signal is None or sample_rate is None:
        cv2.putText(
            image,
            "No audio data",
            (10, height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
        return image

    if not 0 <= audio_channel < audio_signal.shape[0]:
        cv2.putText(
            image,
            f"No audio channel {audio_channel}",
            (10, height // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
        )
        return image

    channel_signal = audio_signal[audio_channel, :]
    samples_per_column = int(np.ceil(channel_signal.shape[0] / width))
    middle_y = height // 2
    cv2.line(image, (0, middle_y), (width - 1, middle_y), (100, 100, 100), 1)

    for x in range(width):
        start = x * samples_per_column
        end = min((x + 1) * samples_per_column, channel_signal.shape[0])
        if start >= end:
            break
        segment = channel_signal[start:end]
        y_min = int((1 - np.max(segment)) * 0.5 * (height - 1))
        y_max = int((1 - np.min(segment)) * 0.5 * (height - 1))
        cv2.line(image, (x, y_min), (x, y_max), foreground, 1)

    return image


def build_spectrogram_image(
    audio_signal,
    sample_rate,
    width,
    height,
    audio_channel,
    background=(24, 24, 24),
    nfft=512,
    noverlap=384,
):
    if (
        audio_signal is None
        or sample_rate is None
        or not 0 <= audio_channel < audio_signal.shape[0]
    ):
        return build_waveform_image(
            audio_signal,
            sample_rate,
            width,
            height,
            audio_channel,
            background,
        )

    signal = audio_signal[audio_channel, :].astype(np.float32)
    dpi = 100
    figure = plt.Figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    canvas = FigureCanvasAgg(figure)
    axes = figure.add_axes([0, 0, 1, 1])
    figure.patch.set_facecolor(np.array(background) / 255.0)
    axes.set_facecolor(np.array(background) / 255.0)
    spectrum, _, _, plot = axes.specgram(
        signal,
        NFFT=nfft,
        Fs=sample_rate,
        noverlap=noverlap,
        scale="dB",
        mode="psd",
        window=np.hanning(nfft),
        cmap="magma",
    )
    decibels = 10.0 * np.log10(spectrum + 1e-12)
    maximum = np.percentile(decibels, 99.5)
    plot.set_clim(maximum - 80.0, maximum)
    axes.set_ylim(0, sample_rate / 2)
    axes.set_axis_off()
    canvas.draw()
    rgba = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
    rgba = rgba.reshape(height, width, 4)
    plt.close(figure)
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)


def draw_playhead(image, position, maximum_position):
    height, width = image.shape[:2]
    if maximum_position <= 0:
        return image
    x = int((float(position) / float(maximum_position)) * (width - 1))
    x = max(0, min(width - 1, x))
    cv2.line(image, (x, 0), (x, height - 1), (0, 180, 255), 1)
    return image


def _point_in_rect(x, y, rectangle):
    x1, y1, x2, y2 = rectangle
    return x1 <= x <= x2 and y1 <= y <= y2


def build_control_bar(width, height, top_y):
    bar = np.full((height, width, 3), (36, 36, 36), dtype=np.uint8)
    cv2.line(bar, (0, 0), (width - 1, 0), (70, 70, 70), 1)
    cv2.line(bar, (0, height - 1), (width - 1, height - 1), (70, 70, 70), 1)
    button_height = 26
    y1 = max(6, (height - button_height) // 2)
    y2 = y1 + button_height
    wave_rectangle = (10, y1, 78, y2)
    spectrogram_rectangle = (84, y1, 152, y2)

    for rectangle, label, selected_mode in (
        (wave_rectangle, "Wave", 0),
        (spectrogram_rectangle, "Spec", 1),
    ):
        color = (70, 125, 190) if show_mode == selected_mode else (48, 48, 48)
        cv2.rectangle(bar, rectangle[:2], rectangle[2:], color, -1)
        cv2.rectangle(bar, rectangle[:2], rectangle[2:], (105, 105, 105), 1)
        cv2.putText(
            bar,
            label,
            (rectangle[0] + 10, rectangle[1] + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (235, 235, 235),
            1,
            cv2.LINE_AA,
        )

    return bar, {
        "wave": (
            wave_rectangle[0],
            top_y + wave_rectangle[1],
            wave_rectangle[2],
            top_y + wave_rectangle[3],
        ),
        "spec": (
            spectrogram_rectangle[0],
            top_y + spectrogram_rectangle[1],
            spectrogram_rectangle[2],
            top_y + spectrogram_rectangle[3],
        ),
    }


def get_zoomed_frame(frame, level, center=None, output_size=None):
    height, width = frame.shape[:2]
    if level <= 1.0:
        if output_size is None or output_size == (width, height):
            return frame
        interpolation = (
            cv2.INTER_AREA
            if output_size[0] < width or output_size[1] < height
            else cv2.INTER_LINEAR
        )
        return cv2.resize(frame, output_size, interpolation=interpolation)

    new_width = int(width / level)
    new_height = int(height / level)
    center_x, center_y = center or (width // 2, height // 2)
    x1 = max(center_x - new_width // 2, 0)
    y1 = max(center_y - new_height // 2, 0)
    x1 = min(x1, width - new_width)
    y1 = min(y1, height - new_height)
    cropped = frame[y1 : y1 + new_height, x1 : x1 + new_width]
    return cv2.resize(
        cropped,
        output_size or (width, height),
        interpolation=cv2.INTER_LINEAR,
    )


def mouse_callback(event, x, y, flags, param):
    del param
    global zoom_level, zoom_center, show_mode

    if event == cv2.EVENT_LBUTTONDOWN:
        if control_regions.get("wave") and _point_in_rect(
            x, y, control_regions["wave"]
        ):
            show_mode = 0
            return
        if control_regions.get("spec") and _point_in_rect(
            x, y, control_regions["spec"]
        ):
            show_mode = 1
            return

    if event == cv2.EVENT_MOUSEWHEEL and display_video_size:
        if y >= display_video_size[1]:
            return
        zoom_level = (
            min(zoom_level + 0.2, 5.0)
            if flags > 0
            else max(zoom_level - 0.2, 1.0)
        )
        if source_video_size:
            display_width, display_height = display_video_size
            source_width, source_height = source_video_size
            zoom_center = (
                int(x * source_width / max(1, display_width)),
                int(y * source_height / max(1, display_height)),
            )


def recording_name(video_path):
    name = Path(video_path).stem
    for suffix in ("_cam1", "_cam2"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


def annotation_path(video_path, root_dir):
    return root_dir / ANNOTATIONS_FOLDER_NAME / f"{recording_name(video_path)}.json"


def durations_match(total_frames, fps, audio_sample_rate, audio_signal, eps=0.1):
    if audio_sample_rate is None or audio_signal is None:
        return False
    video_duration = total_frames / fps
    audio_duration = audio_signal.shape[1] / audio_sample_rate
    return abs(video_duration - audio_duration) < eps


def playable_video_path(input_path):
    codec_check = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ],
        capture_output=True,
        text=True,
    )
    if codec_check.returncode == 0 and codec_check.stdout.strip() == "h264":
        return Path(input_path), False

    temporary_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    temporary_path = Path(temporary_file.name)
    temporary_file.close()
    conversion = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "23",
            "-an",
            str(temporary_path),
        ],
        capture_output=True,
        text=True,
    )
    if conversion.returncode == 0 and temporary_path.exists():
        print(f"Using a temporary H.264 copy for {input_path.name}.")
        return temporary_path, True

    temporary_path.unlink(missing_ok=True)
    print(
        f"Could not create an H.264 copy of {input_path.name}; "
        "opening the original video."
    )
    if conversion.stderr:
        print(conversion.stderr.strip())
    return Path(input_path), False


def load_existing_annotations(json_path):
    if not json_path.exists():
        return {}, {}
    try:
        with json_path.open(encoding="utf-8") as input_file:
            data = json.load(input_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read existing annotations from {json_path}: {exc}")
        return {}, {}
    return data, data.get("video_annotations", {})


def merge_annotations(
    video_path,
    new_annotations,
    audio_path,
    should_update_audio,
    root_dir,
):
    json_path = annotation_path(video_path, root_dir)
    existing_data, _ = load_existing_annotations(json_path)
    existing_data["video_file"] = video_path.name
    existing_data.setdefault("video_annotations", {})

    if should_update_audio:
        existing_data["audio_file"] = audio_path.name
        existing_data.setdefault("audio_annotations", {})

    for event_number, annotation in new_annotations.items():
        existing_data["video_annotations"][event_number] = {
            "time": annotation["time"],
            "frame": annotation["frame"],
        }
        if should_update_audio and annotation["sample"] is not None:
            existing_data["audio_annotations"][event_number] = {
                "time": annotation["time"],
                "sample": int(annotation["sample"]),
            }

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as output_file:
        json.dump(existing_data, output_file, indent=4)
    print(f"Annotations for {video_path.name} updated in {json_path}.")


def update_annotations(annotations, event_number, frame, time_in_seconds, sample_rate):
    print(
        f"Event {event_number} annotated at frame {frame}, "
        f"time {time_in_seconds:.2f}s"
    )
    annotations[str(event_number)] = {
        "frame": frame,
        "time": time_in_seconds,
        "sample": time_in_seconds * sample_rate if sample_rate is not None else None,
    }


def annotations_title(existing_annotations, new_annotations):
    parts = []
    if existing_annotations:
        values = []
        for key, value in existing_annotations.items():
            frame = value.get("frame")
            timestamp = value.get("time")
            if frame is not None and timestamp is not None:
                values.append(f"{key}: F(T): {frame}({timestamp:.2f}s)")
        if values:
            parts.append("Existing: " + " ".join(values))
    if new_annotations:
        values = [
            f"{key}: F(T): {value['frame']}({value['time']:.2f}s)"
            for key, value in sorted(new_annotations.items(), key=lambda item: int(item[0]))
        ]
        parts.append("New: " + " ".join(values))
    return " | ".join(parts)


def annotate_video(video_path, audio_path, root_dir, audio_channel):
    global zoom_level, zoom_center, last_frame
    global display_video_size, source_video_size, control_regions

    zoom_level = 1.0
    zoom_center = None
    playable_path, is_temporary = playable_video_path(video_path)
    capture = cv2.VideoCapture(str(playable_path))
    if not capture.isOpened():
        if is_temporary:
            playable_path.unlink(missing_ok=True)
        print(f"Error: could not open {video_path}.")
        return "next"

    audio_sample_rate = None
    audio_data = None
    audio_duration = 0.0
    if audio_path is not None and audio_path.exists():
        try:
            audio_sample_rate, audio_data = read_wave(audio_path)
            audio_duration = audio_data.shape[1] / audio_sample_rate
        except Exception as exc:
            print(f"Error reading audio file {audio_path}: {exc}")
    elif audio_path is not None:
        print(f"No matching audio file: {audio_path}")

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW_NAME, mouse_callback)
    json_path = annotation_path(video_path, root_dir)
    _, existing_annotations = load_existing_annotations(json_path)
    annotations = {}
    paused = False
    frame_buffer = []
    buffer_index = -1
    quit_application = False
    go_previous = False
    last_restored_key = None

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    video_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    video_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    layout = calculate_display_layout(video_width, video_height)
    display_video_size = (layout["video_width"], layout["video_height"])
    source_video_size = (video_width, video_height)
    plot_width = layout["plot_width"]
    plot_height = layout["plot_height"]
    control_height = layout["control_height"]
    base_waveform = build_waveform_image(
        audio_data,
        audio_sample_rate,
        plot_width,
        plot_height,
        audio_channel,
    )
    base_spectrogram = build_spectrogram_image(
        audio_data,
        audio_sample_rate,
        plot_width,
        plot_height,
        audio_channel,
    )
    audio_player = AudioPlayer(audio_data, audio_sample_rate, audio_channel)
    audio_player.play(0)

    try:
        while True:
            if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                quit_application = True
                break

            if not frame_buffer:
                success, frame = capture.read()
                if not success:
                    break
                frame_buffer.append(frame)

            if not paused:
                if buffer_index < len(frame_buffer) - 1:
                    buffer_index += 1
                else:
                    success, frame = capture.read()
                    if success:
                        frame_buffer.append(frame)
                        buffer_index += 1
                    else:
                        paused = True
                        audio_player.pause()

            frame = frame_buffer[buffer_index]
            last_frame = frame.copy()
            frame_index = buffer_index
            time_in_seconds = frame_index / fps
            display_frame = get_zoomed_frame(
                frame, zoom_level, zoom_center, display_video_size
            )
            audio_plot = (
                base_waveform.copy() if show_mode == 0 else base_spectrogram.copy()
            )
            if audio_duration > 0:
                draw_playhead(audio_plot, time_in_seconds, audio_duration)
            controls, control_regions = build_control_bar(
                plot_width, control_height, display_frame.shape[0]
            )
            combined = np.vstack([display_frame, controls, audio_plot])

            title = f"{video_path.name} | {frame_index}({time_in_seconds:.2f}s)"
            event_summary = annotations_title(existing_annotations, annotations)
            if event_summary:
                title += " | " + event_summary
            cv2.setWindowTitle(WINDOW_NAME, title)
            cv2.imshow(WINDOW_NAME, combined)
            key = cv2.waitKey(max(1, int(round(1000 / fps))))

            if key == 27:
                quit_application = True
                break
            if key == 32:
                paused = not paused
                if paused:
                    audio_player.pause()
                else:
                    audio_player.play(time_in_seconds)
            elif key == ord("r"):
                zoom_level = 1.0
                zoom_center = None
            elif ord("1") <= key <= ord("8") and not ctrl_pressed:
                number = key - ord("0")
                previous = annotations.get(str(number - 1)) if number > 1 else None
                if number == 1 or (
                    previous is not None and previous["frame"] <= frame_index
                ):
                    for later_number in range(number, 9):
                        annotations.pop(str(later_number), None)
                    update_annotations(
                        annotations,
                        number,
                        frame_index,
                        time_in_seconds,
                        audio_sample_rate,
                    )
            elif key == ord("n"):
                break
            elif key == ord("p"):
                go_previous = True
                break
            elif key == ord("c"):
                annotations.clear()

            if ctrl_pressed and event_key in tuple(str(number) for number in range(1, 9)):
                if event_key != last_restored_key and event_key in existing_annotations:
                    restored = existing_annotations[event_key]
                    update_annotations(
                        annotations,
                        int(event_key),
                        restored["frame"],
                        restored["time"],
                        audio_sample_rate,
                    )
                last_restored_key = event_key
            else:
                last_restored_key = None

            if paused and key == ord("a") and buffer_index > 0:
                buffer_index -= 1
                audio_player.seek(buffer_index / fps)
            elif paused and key == ord("d"):
                if buffer_index < len(frame_buffer) - 1:
                    buffer_index += 1
                    audio_player.seek(buffer_index / fps)
                else:
                    success, frame = capture.read()
                    if success:
                        frame_buffer.append(frame.copy())
                        buffer_index += 1
                        audio_player.seek(buffer_index / fps)
    finally:
        audio_player.stop()
        capture.release()
        cv2.destroyAllWindows()
        if is_temporary:
            playable_path.unlink(missing_ok=True)

    if annotations:
        should_update_audio = durations_match(
            total_frames,
            fps,
            audio_sample_rate,
            audio_data,
        )
        merge_annotations(
            video_path,
            annotations,
            audio_path,
            should_update_audio,
            root_dir,
        )
    else:
        print(f"No annotations made for {video_path.name}.")

    if quit_application:
        return "quit"
    if go_previous:
        return "previous"
    return "next"


def configured_audio_dir(root_dir):
    setup_path = root_dir / SETUP_FILENAME
    if setup_path.exists():
        try:
            with setup_path.open(encoding="utf-8") as setup_file:
                setup_data = json.load(setup_file)
            configured_path = setup_data.get("local_dir")
            if configured_path:
                audio_dir = Path(configured_path)
                return audio_dir if audio_dir.is_absolute() else root_dir / audio_dir
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Could not read {setup_path}: {exc}")
    return root_dir / DEFAULT_AUDIO_FOLDER_NAME


def process_videos(camera, audio_channel=DEFAULT_AUDIO_CHANNEL):
    root_dir = Path.cwd()
    video_dir = root_dir / VIDEO_FOLDER_NAME
    audio_dir = configured_audio_dir(root_dir)
    if not video_dir.is_dir():
        raise FileNotFoundError(f"Video directory does not exist: {video_dir}")

    camera_suffix = f"_{camera}"
    videos = sorted(
        path
        for path in video_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in (".mp4", ".webm")
        and path.stem.lower().endswith(camera_suffix)
    )
    if not videos:
        raise FileNotFoundError(
            f"No {camera} recordings found in {video_dir}."
        )

    index = 0
    while 0 <= index < len(videos):
        video_path = videos[index]
        audio_path = audio_dir / f"{recording_name(video_path)}.wav"
        result = annotate_video(video_path, audio_path, root_dir, audio_channel)
        if result == "quit":
            break
        if result == "previous":
            index = max(0, index - 1)
        else:
            index += 1


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Annotate acquisition videos from the videos/ directory and use "
            "matching audio from local_dir configured in setup.json."
        )
    )
    parser.add_argument(
        "--camera",
        choices=("cam1", "cam2"),
        default="cam1",
        help="Camera recordings to annotate (default: cam1).",
    )
    parser.add_argument(
        "--audio-channel",
        type=int,
        choices=(0, 1),
        default=DEFAULT_AUDIO_CHANNEL,
        help="Audio channel used for playback and visualization (default: 0).",
    )
    return parser.parse_args()


def main():
    global keyboard
    args = parse_args()
    from pynput import keyboard as pynput_keyboard

    keyboard = pynput_keyboard
    listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
    listener.daemon = True
    listener.start()
    try:
        process_videos(args.camera, args.audio_channel)
    finally:
        listener.stop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Create one synchronized CSV from USG, Dobot and camera recordings.

Edit the parameters below, then run:
  python sync_recordings.py
"""

import csv
import glob
import math
import os
import subprocess
from bisect import bisect_left


# Parameters
PREFIX = "Speed-4_2026-04-15_16.07.56"
ROOT = "."
OUT_DIR = "synced"

# "auto" chooses the fastest available timeline. You can also use: "camera", "usg", "dobot".
TIMELINE = "auto"

# True cuts start to the latest-started device and end to the earliest-stopped device.
# False keeps the whole span and leaves blanks where a device is missing.
CUT_TO_COMMON_RANGE = True

CAMERA_FPS = 30.0
MAX_GAP = 0.20


def read_csv_rows(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def read_camera_start(root):
    path = os.path.join(root, "video_timestamps", f"{PREFIX}.csv")
    return float(read_csv_rows(path)[0]["start_timestamp"])


def read_usg(path):
    rows = []
    for row in read_csv_rows(path):
        rows.append({
            "time": float(row["timestamp"]),
            "frame": int(row["frame_index"]),
        })
    return sorted(rows, key=lambda row: row["time"])


def read_dobot(path):
    rows = []
    for index, row in enumerate(read_csv_rows(path)):
        rows.append({
            "index": index,
            "time": float(row["timestamp"]),
            "x": float(row["x"]),
            "y": float(row["y"]),
            "z": float(row["z"]),
            "r": float(row["r"]),
        })
    return sorted(rows, key=lambda row: row["time"])


def average_rate(times):
    duration = times[-1] - times[0]
    return (len(times) - 1) / duration


def nearest_index(times, target_time):
    index = bisect_left(times, target_time)
    candidates = []
    if index > 0:
        candidates.append(index - 1)
    if index < len(times):
        candidates.append(index)
    return min(candidates, key=lambda i: abs(times[i] - target_time))


def nearest_time_difference(times, target_time):
    if target_time < times[0] or target_time > times[-1]:
        return None
    nearest = nearest_index(times, target_time)
    return abs(times[nearest] - target_time)


def nearest_camera_difference(target_time, frame_count, camera_start):
    second = target_time - camera_start
    frame = int(round(second * CAMERA_FPS))
    if second < 0:
        return None
    if frame >= frame_count:
        return None
    frame_time = camera_start + frame / CAMERA_FPS
    return abs(frame_time - target_time)


def interpolate_number(left, right, ratio):
    return left + (right - left) * ratio


def usg_at(rows, times, target_time):
    empty = {
        "usg_frame": "",
        "usg_nearest_frame": "",
    }
    if target_time < times[0] or target_time > times[-1]:
        return empty

    nearest = nearest_index(times, target_time)
    nearest_row = rows[nearest]
    result = dict(empty)
    result["usg_nearest_frame"] = nearest_row["frame"]
    nearest_dt = nearest_row["time"] - target_time

    if abs(nearest_dt) < 1e-9:
        result["usg_frame"] = float(nearest_row["frame"])
        return result

    index = bisect_left(times, target_time)
    if 0 < index < len(rows):
        left = rows[index - 1]
        right = rows[index]
        left_gap = target_time - left["time"]
        right_gap = right["time"] - target_time
        if left_gap <= MAX_GAP and right_gap <= MAX_GAP:
            ratio = left_gap / (right["time"] - left["time"])
            result["usg_frame"] = interpolate_number(left["frame"], right["frame"], ratio)
            return result

    if abs(nearest_dt) <= MAX_GAP:
        result["usg_frame"] = float(nearest_row["frame"])
    return result


def dobot_at(rows, times, target_time):
    empty = {
        "dobot_x": "",
        "dobot_y": "",
        "dobot_z": "",
        "dobot_r": "",
    }
    if target_time < times[0] or target_time > times[-1]:
        return empty

    nearest = nearest_index(times, target_time)
    nearest_row = rows[nearest]
    result = dict(empty)
    nearest_dt = nearest_row["time"] - target_time

    if abs(nearest_dt) < 1e-9:
        for axis in ("x", "y", "z", "r"):
            result[f"dobot_{axis}"] = nearest_row[axis]
        return result

    index = bisect_left(times, target_time)
    if 0 < index < len(rows):
        left = rows[index - 1]
        right = rows[index]
        left_gap = target_time - left["time"]
        right_gap = right["time"] - target_time
        if left_gap <= MAX_GAP and right_gap <= MAX_GAP:
            ratio = left_gap / (right["time"] - left["time"])
            for axis in ("x", "y", "z", "r"):
                result[f"dobot_{axis}"] = interpolate_number(left[axis], right[axis], ratio)
            return result

    if abs(nearest_dt) <= MAX_GAP:
        for axis in ("x", "y", "z", "r"):
            result[f"dobot_{axis}"] = nearest_row[axis]
    return result


def camera_at(target_time, frame_count, camera_start):
    empty = {
        "camera_second": "",
        "camera_frame": "",
    }

    second = target_time - camera_start
    frame = int(round(second * CAMERA_FPS))

    if second < 0:
        return empty
    if frame >= frame_count:
        return empty

    return {
        "camera_second": second,
        "camera_frame": frame,
    }


def count_video_frames(path):
    command = [
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames",
        "-of", "default=nokey=1:noprint_wrappers=1", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
    return int(result.stdout.splitlines()[0].strip())


def camera_frame_count(root):
    counts = []
    for camera in ("cam1", "cam2"):
        pattern = os.path.join(root, "videos", f"{PREFIX}_{camera}.*")
        matches = sorted(glob.glob(pattern))
        counts.append(count_video_frames(matches[0]))
    return min(counts)


def choose_timeline(usg_times, dobot_times):
    if TIMELINE != "auto":
        return TIMELINE

    choices = [
        (average_rate(usg_times), "usg"),
        (average_rate(dobot_times), "dobot"),
        (CAMERA_FPS, "camera"),
    ]
    return max(choices, key=lambda item: item[0])[1]


def synchronization_range(usg_times, dobot_times, frame_count, camera_start):
    starts = [("usg", usg_times[0]), ("dobot", dobot_times[0])]
    ends = [("usg", usg_times[-1]), ("dobot", dobot_times[-1])]

    starts.append(("camera", camera_start))
    camera_end = camera_start + (frame_count - 1) / CAMERA_FPS
    ends.append(("camera", camera_end))

    if CUT_TO_COMMON_RANGE:
        start_source, start = max(starts, key=lambda item: item[1])
        end_source, end = min(ends, key=lambda item: item[1])
    else:
        start_source, start = min(starts, key=lambda item: item[1])
        end_source, end = max(ends, key=lambda item: item[1])

    if end < start:
        raise RuntimeError("Streams do not overlap")
    return start, end, start_source, end_source


def timeline_samples(timeline, start, end, usg_rows, dobot_rows, frame_count, camera_start):
    if timeline == "usg":
        for row in usg_rows:
            if start <= row["time"] <= end:
                yield row["time"], row["frame"]
        return

    if timeline == "dobot":
        for row in dobot_rows:
            if start <= row["time"] <= end:
                yield row["time"], row["index"]
        return

    if timeline == "camera":
        first_frame = math.ceil((start - camera_start) * CAMERA_FPS - 1e-9)
        last_frame = math.floor((end - camera_start) * CAMERA_FPS + 1e-9)
        last_frame = min(last_frame, frame_count - 1)

        for frame in range(first_frame, last_frame + 1):
            time = camera_start + frame / CAMERA_FPS
            if start <= time <= end:
                yield time, frame

    else:
        raise ValueError(f"Unknown timeline: {timeline}")


def fmt(value, digits=6):
    if value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return value


def write_output_csv(root, out_dir):
    usg_rows = read_usg(os.path.join(root, "usg_timestamps", f"{PREFIX}.csv"))
    dobot_rows = read_dobot(os.path.join(root, "dobot", f"{PREFIX}.csv"))
    usg_times = [row["time"] for row in usg_rows]
    dobot_times = [row["time"] for row in dobot_rows]
    camera_start = read_camera_start(root)
    frame_count = camera_frame_count(root)

    timeline = choose_timeline(usg_times, dobot_times)
    start, end, start_source, end_source = synchronization_range(
        usg_times, dobot_times, frame_count, camera_start
    )

    os.makedirs(out_dir, exist_ok=True)
    output_path = os.path.join(out_dir, f"{PREFIX}_{timeline}_sync.csv")

    columns = [
        "time",
        "timeline",
        "master_index",
        "usg_frame",
        "usg_nearest_frame",
        "dobot_x",
        "dobot_y",
        "dobot_z",
        "dobot_r",
        "camera_second",
        "camera_frame",
    ]

    rows_written = 0
    with open(output_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        max_difference = {"usg": 0.0, "dobot": 0.0, "camera": 0.0}

        for time, master_index in timeline_samples(
            timeline, start, end, usg_rows, dobot_rows, frame_count, camera_start
        ):
            row = {
                "time": time,
                "timeline": timeline,
                "master_index": master_index,
            }
            row.update(usg_at(usg_rows, usg_times, time))
            row.update(dobot_at(dobot_rows, dobot_times, time))
            row.update(camera_at(time, frame_count, camera_start))

            for name, difference in (
                ("usg", nearest_time_difference(usg_times, time)),
                ("dobot", nearest_time_difference(dobot_times, time)),
                ("camera", nearest_camera_difference(time, frame_count, camera_start)),
            ):
                if difference is not None:
                    max_difference[name] = max(max_difference[name], difference)

            row = {key: row.get(key, "") for key in columns}

            for key in list(row):
                if key in ("dobot_x", "dobot_y", "dobot_z", "dobot_r"):
                    row[key] = fmt(row[key], 4)
                else:
                    row[key] = fmt(row[key])

            writer.writerow(row)
            rows_written += 1

    print(f"Wrote {output_path}")
    print(f"timeline={timeline}, rows={rows_written}, start_by={start_source}, end_by={end_source}")
    print("Max nearest-sample time difference after synchronization:")
    for name in ("usg", "dobot", "camera"):
        seconds = max_difference[name]
        print(f"  {name}: {seconds:.6f} s ({seconds * 1000:.2f} ms)")


def main():
    root = os.path.abspath(ROOT)
    out_dir = os.path.abspath(os.path.join(root, OUT_DIR))
    write_output_csv(root, out_dir)


if __name__ == "__main__":
    main()

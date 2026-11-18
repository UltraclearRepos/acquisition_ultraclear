import argparse
import os
from pathlib import Path
import cv2
import cv2.aruco as aruco
import pandas as pd
import numpy as np
from tqdm.auto import tqdm
import json
from ..config import AUDIO_RAW_DIR, CAMERA_VIDEO_DIRS
from ..synchronize import read_wave

POSITIONS_FOLDER_NAME = "labelled_positions"
ANNOTATIONS_FOLDER_NAME = "annotations"

camera_matrix = np.array([[630.41, 0.0, 640],
                            [0.0, 631.93, 353],
                            [0.0, 0.0, 1.0]])

dist_coeffs = np.array([0.14, -0.44, 0.0, 0.0, 0.31])

ANNOTATION_AXIS = "Y"

def estimate_pose_single_markers(corners, marker_length):
    """
    Replacement for aruco.estimatePoseSingleMarkers, which is not available
    in OpenCV 4.7+. Uses the same marker coordinate system, solver
    (default solvePnP) and output shapes.
    """
    half = marker_length / 2.0
    marker_points = np.array([
        [-half, half, 0.0],
        [half, half, 0.0],
        [half, -half, 0.0],
        [-half, -half, 0.0]
    ], dtype=np.float32)

    rvecs = []
    tvecs = []
    for c in corners:
        _, rvec, tvec = cv2.solvePnP(
            marker_points,
            c.reshape(-1, 2).astype(np.float32),
            camera_matrix,
            dist_coeffs
        )
        rvecs.append(rvec.reshape(1, 3))
        tvecs.append(tvec.reshape(1, 3))

    return np.array(rvecs), np.array(tvecs), None

def show_video_frame(frame, fps, display):
    if not display:
        return True

    cv2.imshow('Aruco Tracking', frame)
    sleep_time = 1000 // fps
    key = cv2.waitKey(sleep_time) & 0xFF
    return key != ord("q")


def durations_match(df, audio_sr, audio_signal, fps, tolerance=0.1):

    total_frames = df['Frame'].max()

    video_duration = total_frames / fps
    audio_duration = audio_signal.shape[1] / audio_sr

    return abs(video_duration - audio_duration) <= tolerance


def process_data(df, video_path, audio_path, positions_folder, annotations_folder, distances_file_path, output_name, fps=30):
    os.makedirs(positions_folder, exist_ok=True)
    os.makedirs(annotations_folder, exist_ok=True)

    calculate_speed(df, fps=fps)
    positions_output_path = os.path.join(positions_folder, f'{output_name}.csv')

    df.to_csv(positions_output_path, index=False)

    create_annotations(df, video_path, audio_path, annotations_folder, distances_file_path, output_name, fps=fps)

def calculate_speed(df, fps=30, frame_interval=1):
    dt = frame_interval / fps

    df['dx'] = df['Object_X_cm'].shift(-frame_interval) - df['Object_X_cm']
    df['dy'] = df['Object_Y_cm'].shift(-frame_interval) - df['Object_Y_cm']
    df['dz'] = df['Object_Z_cm'].shift(-frame_interval) - df['Object_Z_cm']

    df['velocity_cm/s'] = df[f'd{ANNOTATION_AXIS.lower()}'] / dt
    df['velocity_all_cm/s'] = np.sqrt(df['dx']**2 + df['dy']**2 + df['dz']**2) / dt

    return df

def create_annotations(df, video_path, audio_path, annotations_folder, distances_file_path, output_name, fps=30):
    df = df.copy()
    df.reset_index(drop=True, inplace=True)

    video_file = os.path.basename(video_path)
    position_column = f'Object_{ANNOTATION_AXIS}_cm'

    if audio_path is not None and os.path.isfile(audio_path):
        audio_sr, audio_signal = read_wave(audio_path)
        data_synchronized = durations_match(df, audio_sr, audio_signal, fps=fps)
    else:
        return

    distances = read_distances_from_file(distances_file_path)
    if distances:
        increasing = distances[-1] > distances[0]
        video_annotations = {}
        audio_annotations = {} if audio_path is not None and data_synchronized else None

        coordinate_values = df[position_column].dropna()
        end_idx = coordinate_values.idxmax() if increasing else coordinate_values.idxmin()
        segment = df.loc[:end_idx]

        tracked_high = segment[segment[position_column].notna()].copy()
        tracked_high['velocity_mean'] = tracked_high['velocity_cm/s'].rolling(window=5, min_periods=2).mean()

        for idx, distance in enumerate(distances, start=1):
            coordinate = tracked_high[position_column]
            velocity_mean = tracked_high['velocity_mean']

            if increasing:
                cross_condition = (coordinate.shift(1) < distance) & (coordinate.shift(-1) > distance)
                velocity_condition = (velocity_mean > 0)
            else:
                cross_condition = (coordinate.shift(1) > distance) & (coordinate.shift(-1) < distance)
                velocity_condition = (velocity_mean < 0)

            candidates = tracked_high[cross_condition & velocity_condition]

            if not candidates.empty:
                chosen_row = candidates.iloc[0]
            else:
                mask_moving_down = velocity_condition
                if mask_moving_down.any():
                    diffs = (coordinate - distance).abs()
                    best_idx = diffs[mask_moving_down].idxmin()
                    chosen_row = tracked_high.loc[best_idx]
                else:
                    diffs = (coordinate - distance).abs()
                    best_idx = diffs.idxmin()
                    chosen_row = tracked_high.loc[best_idx]

            video_annotations[str(idx)] = {
                "frame": chosen_row["Frame"],
                "time": chosen_row["Time (s)"]
            }
            if data_synchronized:
                audio_annotations[str(idx)] = {
                    "sample": int(chosen_row["Time (s)"] * audio_sr),
                    "time": chosen_row["Time (s)"]
                }

        annotations_output_path = os.path.join(annotations_folder, f'{output_name}.json')
        if data_synchronized:
            payload = {
                "audio_file": f'{os.path.basename(audio_path)}',
                "video_file": video_file,
                "video_annotations": video_annotations,
                "audio_annotations": audio_annotations
            }
        else:
            payload = {
                "video_file": video_file,
                "video_annotations": video_annotations,
            }
        with open(annotations_output_path, "w") as f:
            json.dump(payload, f, indent=4)

def read_distances_from_file(file_path):


    if file_path is None or not os.path.isfile(file_path):
        print(f'Distance file for annotations not found, skipping annotating.')
        return []

    try:
        with open(file_path, 'r') as f:
            raw = f.read().strip()
        distances = [float(distance.strip()) for distance in raw.split(',') if distance.strip() != ""]
        return distances
    except Exception as e:
        print(f"Error reading distances from file {file_path}: {e}")
        return []

"""
Tracking without cube section
"""

def track_aruco_no_cube(
        video_path,
        dobot_mode,
        marker_length_obj,
        marker_margin_obj,
        needle_offset,
        axis_length=4,
        starting_position=14,
        z_offset=None,
        table_offset=0.0,
        fps=30,
        display=True
    ):

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return pd.DataFrame()

    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    params = aruco.DetectorParameters()
    detector = aruco.ArucoDetector(dictionary, params)

    height_constraint = None
    results = []
    frame_idx = 1

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        corners_all, ids_all, _ = detector.detectMarkers(frame)
        corners = []
        if ids_all is not None and len(ids_all) > 0:
            corners_all = list(corners_all)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            for c, marker_idx in zip(corners_all, ids_all.flatten()):
                if marker_idx == 0:
                    refined = cv2.cornerSubPix(
                        gray, c,
                        winSize=(5,5),
                        zeroZone=(-1,-1),
                        criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 300, 0.001)
                    )
                    corners.append(refined)

        if corners and len(corners) > 0:
            ids = np.array([0], dtype=np.int32)
            aruco.drawDetectedMarkers(frame, corners, ids)
            rvecs, tvecs, _ = estimate_pose_single_markers(corners, marker_length_obj)

            attachment_offset = marker_length_obj / 2 + marker_margin_obj
            if dobot_mode:

                if z_offset is None:
                    z_offset = 2.2

                r_o = rvecs[0].reshape(3, 1)
                t_o = tvecs[0].reshape(3, 1)
                R_o, _ = cv2.Rodrigues(r_o)

                t_o = (R_o @ np.array([[0.0, 0.0, -z_offset]], dtype=np.float32).T + t_o).flatten()
                t_final = (np.array([0.0, attachment_offset + needle_offset, 0.0], dtype=np.float32) + t_o)

                x = t_final[0]
                y = (t_final[1] * -1) - table_offset
                z = t_final[2]
            else:

                if z_offset is None:
                    z_offset = 0.0

                needle_coord = np.array([[0.0, -attachment_offset - needle_offset, -z_offset]], dtype=np.float32)

                r_o = rvecs[0].reshape(3, 1)
                t_o = tvecs[0].reshape(3, 1)
                R_o, _ = cv2.Rodrigues(r_o)

                t_final = (R_o @ needle_coord.T + t_o).flatten()

                x = t_final[0]
                y = (t_final[1] * -1) - table_offset
                z = t_final[2]

            if height_constraint is None:
                height_constraint = y

            y = y - height_constraint + starting_position

            ### Helper line to labelling
            pts = corners[0].reshape(-1, 2)
            cx, cy = pts.mean(axis=0).astype(int)
            h, w = frame.shape[:2]
            cv2.line(frame, (0, cy), (w, cy), (0, 255, 0), 1)

            tip2d, _ = cv2.projectPoints(
                np.array([t_final], dtype=np.float32),
                np.zeros((3, 1)), np.zeros((3, 1)),
                camera_matrix, dist_coeffs
            )
            u, v = tip2d.ravel().astype(int)

            cv2.line(frame, (0, v), (w, v), (0, 255, 0), 1)
            ### Helper line to labelling

            cv2.drawFrameAxes(frame, camera_matrix, dist_coeffs, r_o, t_o, axis_length)

            text = f'Position: X: {x:.2f}, Y: {y:.2f}, Z: {z:.2f}'
            corner = tuple(corners[0][0][0].astype(int))
            cv2.putText(frame, text, (corner[0], corner[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            results.append([frame_idx, round(frame_idx / fps, ndigits=2), x, y, z])
        else:
            results.append([frame_idx, round(frame_idx / fps, ndigits=2), None, None, None])

        cv2.imwrite(f'tracked_frames/frame_{frame_idx}.jpg', frame)

        if not show_video_frame(frame, fps, display):
            break

        frame_idx += 1

    cap.release()
    cv2.destroyAllWindows()
    df = pd.DataFrame(results, columns=['Frame', 'Time (s)', 'Object_X_cm', 'Object_Y_cm', 'Object_Z_cm'])
    return df

"""
Tracking with cube section
"""

def make_corners(xc, yc, zc, m_len, axis):
    """
    Order: [left-top, right-top, right-bottom, left-bottom]
    """
    mh = m_len / 2.00

    if axis == 'x-': # LEFT
        return np.array([
            [xc, yc + mh, zc - mh],  # left-top
            [xc, yc + mh, zc + mh],  # right-top
            [xc, yc - mh, zc + mh],  # right-bottom
            [xc, yc - mh, zc - mh]   # left-bottom
        ])
    elif axis == 'x+': # RIGHT
        return np.array([
            [xc, yc + mh, zc + mh],  # left-top
            [xc, yc + mh, zc - mh],  # right-top
            [xc, yc - mh, zc - mh],  # right-bottom
            [xc, yc - mh, zc + mh]   # left-bottom
        ])
    elif axis == 'y': # UP / DOWN
        return np.array([
            [xc - mh, yc, zc - mh],  # left-top
            [xc + mh, yc, zc - mh],  # right-top
            [xc + mh, yc, zc + mh],  # right-bottom
            [xc - mh, yc, zc + mh]   # left-bottom
        ])
    elif axis == 'z': # FRONT / BACK
        return np.array([
            [xc - mh, yc + mh, zc],  # left-top
            [xc + mh, yc + mh, zc],  # right-top
            [xc + mh, yc - mh, zc],  # right-bottom
            [xc - mh, yc - mh, zc]   # left-bottom
        ])

def detect_cube_pose(frame, obj_pts_dict=None, min_markers=3, cube_edge_top=5, cube_edge_sides=5, marker_length_cube=3, axis_length=3):

    if obj_pts_dict is None:
        half_edge = cube_edge_top / 2.0
        half_edge_sides = cube_edge_sides / 2.0
        obj_pts_dict = {
            0: make_corners(0.0, half_edge, 0.0, marker_length_cube, 'y'), # TOP
            1: make_corners(0.0, 0.0, half_edge_sides, marker_length_cube, 'z'), # FRONT
            2: make_corners(-half_edge_sides, 0.0, 0.0, marker_length_cube, 'x-') # LEFT
        }

    params = aruco.DetectorParameters()
    dict_cube = aruco.getPredefinedDictionary(aruco.DICT_5X5_100)
    detector_cube = aruco.ArucoDetector(dict_cube, params)

    corners, ids, _ = detector_cube.detectMarkers(frame)
    if ids is None:
        return None

    all_obj, all_img = [], []
    for c, mid in zip(corners, ids.flatten()):
        if mid in obj_pts_dict:
            all_obj.append(obj_pts_dict[mid])
            all_img.append(c.reshape(-1, 2))
    if len(all_obj) < min_markers:
        return None

    obj_pts = np.vstack(all_obj)
    img_pts = np.vstack(all_img)
    _, rvec, tvec = cv2.solvePnP(obj_pts, img_pts, camera_matrix, dist_coeffs)

    R_c, _ = cv2.Rodrigues(rvec)

    ### Display cube detection
    init_frame = frame.copy()
    x_c, y_c, z_c = tvec.flatten()
    text = f'Cube Position: X: {x_c:.2f}cm, Y: {y_c:.2f}cm, Z: {z_c:.2f}cm'
    cv2.putText(init_frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    origin3d = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)

    corners3d = []
    colors = []

    for fid, pts3d in obj_pts_dict.items():
        corners3d.append(pts3d)

        if fid == 0:  # TOP
            col = (0, 255, 0)  # green
        elif fid == 1:  # FRONT
            col = (255, 0, 0)  # blue
        elif fid == 2:  # LEFT
            col = (0, 0, 255)  # red
        elif fid == 3:  # RIGHT
            col = (0, 255, 255)  # yellow
        colors += [col] * 4

    corners3d = np.vstack(corners3d).astype(np.float32)

    all3d = np.vstack([origin3d, corners3d])
    all2d, _ = cv2.projectPoints(
        all3d, rvec, tvec, camera_matrix, dist_coeffs
    )

    all2d = all2d.reshape(-1, 2).astype(int)

    cx, cy = all2d[0]
    cv2.circle(init_frame, (cx, cy), 6, (255, 255, 255), -1)

    for pt, col in zip(all2d[1:], colors):
        cv2.circle(init_frame, tuple(pt), 2, col, -1)

    aruco.drawDetectedMarkers(init_frame, corners, ids)
    cv2.drawFrameAxes(init_frame, camera_matrix, dist_coeffs, rvec, tvec, axis_length)

    return rvec, tvec, R_c.T, corners, ids, init_frame

def track_aruco_cube(
        video_path,
        dobot_mode,
        marker_length_obj,
        marker_margin_obj,
        needle_offset,
        axis_length=4,
        marker_length_cube=3,
        cube_edge_top=5.0,
        cube_edge_sides=5,
        z_offset=None,
        table_offset=0.0,
        fps=30,
        display=True):

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return pd.DataFrame()

    params = aruco.DetectorParameters()
    dict_marker = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    detector_obj = aruco.ArucoDetector(dict_marker, params)

    half_edge = cube_edge_top / 2.0
    cube_data = None

    cube_detection_attempts = 0
    while cube_data is None:
        ret, frame = cap.read()
        if not ret:
            print(f'Could not find cube in video: {video_path}')
            return pd.DataFrame()

        cube_data = detect_cube_pose(
            frame,
            cube_edge_top=cube_edge_top,
            cube_edge_sides=cube_edge_sides,
            marker_length_cube=marker_length_cube,
            axis_length=axis_length
        )
        cube_detection_attempts += 1

    rvec_c, tvec_c, R_inv, corners_c, ids_c, init_frame = cube_data
    r_c = rvec_c.flatten()
    t_c = tvec_c.flatten()

    if display:
        cv2.imshow('Cube Detection', init_frame)
        cv2.waitKey(5000)

    results = []
    frame_idx = 1

    cap.release()
    cap = cv2.VideoCapture(video_path)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        corners_all, ids_all, _ = detector_obj.detectMarkers(frame)
        corners_o = []
        if ids_all is not None and len(ids_all) > 0:
            corners_all = list(corners_all)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            for c, marker_idx in zip(corners_all, ids_all.flatten()):
                if marker_idx == 0:
                    refined_corner = cv2.cornerSubPix(
                        gray, c,
                        winSize=(5,5),
                        zeroZone=(-1,-1),
                        criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
                    )
                    corners_o.append(refined_corner)

        if corners_o and len(corners_o) > 0:
            ids_o = np.array([0], dtype=np.int32)
            aruco.drawDetectedMarkers(frame, corners_o, ids_o)
            rvecs, tvecs, _ = estimate_pose_single_markers(corners_o, marker_length_obj)

            attachment_offset = marker_length_obj / 2 + marker_margin_obj
            if dobot_mode:

                if z_offset is None:
                    z_offset = 2.2

                r_o = rvecs[0]
                t_o = tvecs[0].reshape(3, 1)
                R_o, _ = cv2.Rodrigues(r_o)

                t_o = (R_o @ np.array([[0.0, 0.0, -z_offset]], dtype=np.float32).T + t_o).flatten()
                t_needle = (np.array([0.0, attachment_offset + needle_offset, 0.0], dtype=np.float32) + t_o)
                t_final = R_inv.dot(t_needle - t_c)

                x = t_final[0]
                y = t_final[1] + half_edge - table_offset
                z = t_final[2]
            else:

                if z_offset is None:
                    z_offset = 0.0

                needle_coord = np.array([[0.0, -attachment_offset - needle_offset, -z_offset]], dtype=np.float32)

                r_o = rvecs[0].reshape(3, 1)
                t_o = tvecs[0].reshape(3, 1)
                R_o, _ = cv2.Rodrigues(r_o)

                t_needle = (R_o @ needle_coord.T + t_o).flatten()
                t_final = R_inv.dot(t_needle - t_c)

                x = t_final[0]
                y = t_final[1] + half_edge - table_offset
                z = t_final[2]

            ### Helper line to labelling
            pts = corners_o[0].reshape(-1, 2)
            cx, cy = pts.mean(axis=0).astype(int)
            h, w = frame.shape[:2]
            cv2.line(frame, (0, cy), (w, cy), (0, 255, 0), 1)

            tip2d, _ = cv2.projectPoints(
                np.array([t_final], dtype=np.float32),
                rvec_c, tvec_c,
                camera_matrix, dist_coeffs
            )
            u, v = tip2d.ravel().astype(int)

            cv2.line(frame, (0, v), (w, v), (0, 255, 0), 1)
            # cv2.circle(frame, (u, v), 3, (0, 0, 255), -1)
            ### Helper line to labelling

            cv2.drawFrameAxes(frame, camera_matrix, dist_coeffs, r_o, t_o, axis_length)

            text = f'Position: X: {x:.2f}, Y: {y:.2f}, Z: {z:.2f}'
            corner = tuple(corners_o[0][0][0].astype(int))
            cv2.putText(frame, text, (corner[0], corner[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            results.append([frame_idx, round(frame_idx / fps, ndigits=2), x, y, z])
        else:
            results.append([frame_idx, round(frame_idx / fps, ndigits=2), np.nan, np.nan, np.nan])

        cv2.imwrite(f'tracked_frames/frame_{frame_idx}.jpg', frame)
        if not show_video_frame(frame, fps, display):
            break

        frame_idx += 1

    cap.release()
    cv2.destroyAllWindows()
    df = pd.DataFrame(results, columns=['Frame', 'Time (s)', 'Object_X_cm', 'Object_Y_cm', 'Object_Z_cm'])
    return df

def run_aruco_tracking_for_folder(
        root_dir,
        camera,
        cube_mode,
        dobot_mode,
        marker_length_obj,
        marker_margin_obj,
        needle_offset,
        starting_position=0.0,
        z_offset=None,
        table_offset=0.0,
        fps=30,
        distances_path=None,
        display=True
    ):
    video_folder_path = root_dir / CAMERA_VIDEO_DIRS[camera]
    audio_folder_path = root_dir / AUDIO_RAW_DIR

    if not video_folder_path.is_dir():
        print(f"Error: Folder {video_folder_path} does not exist.")
        return

    if not audio_folder_path.is_dir():
        print(f"Audio folder {audio_folder_path} not found, will not produce audio annotations.")

    video_paths = sorted(
        path
        for path in video_folder_path.iterdir()
        if path.is_file()
        and path.suffix.lower() in (".mp4", ".webm")
    )

    if len(video_paths) > 0:
        print(f"Running for {camera} videos in {video_folder_path}: {len(video_paths)} files")

    positions_folder = root_dir / POSITIONS_FOLDER_NAME
    annotations_folder = root_dir / ANNOTATIONS_FOLDER_NAME

    for i, video_path in enumerate(
        tqdm(video_paths, desc=f'Folder: {video_folder_path}', unit='video'),
        start=1
    ):
        tqdm.write(f"Processing ({i}/{len(video_paths)}): {video_path.name}")
        if(cube_mode):
            df = track_aruco_cube(
                str(video_path),
                dobot_mode,
                marker_length_obj,
                marker_margin_obj,
                needle_offset,
                z_offset=z_offset,
                table_offset=table_offset,
                fps=fps,
                display=display
            )
        else:
            df = track_aruco_no_cube(
                str(video_path),
                dobot_mode,
                marker_length_obj,
                marker_margin_obj,
                needle_offset,
                starting_position=starting_position,
                z_offset=z_offset,
                table_offset=table_offset,
                fps=fps,
                display=display
            )

        if not df.empty and 'Object_Y_cm' in df and df["Object_Y_cm"].notna().any():
            audio_path = audio_folder_path / f"{video_path.stem}.wav"
            output_name = video_path.stem
            process_data(df, str(video_path), str(audio_path), str(positions_folder), str(annotations_folder), distances_path, output_name, fps=fps)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Tool for annotating position of needle in videos from the video_cam1/ or video_cam2/ folder. " \
        "Matching audio files are read from the audio_raw/ folder. " \
        "Positions are saved in the labelled_positions/ folder. " \
        "When you provide distances.txt file, it will produce annotations in the annotations/ folder. " \
        "distances.txt file should look like: 12,8.5,7,5.4"
    )
    parser.add_argument("--root-dir", type=Path, default=Path.cwd(), help="Directory containing video_cam1/, video_cam2/ and audio_raw/ folders (default: current directory).")
    parser.add_argument("--camera", choices=("cam1", "cam2"), default="cam1", help="Camera recordings to track (default: cam1).")
    parser.add_argument("--marker-length", required=True, type=float, help="Length of the Aruco marker in cm (From protocol)")
    parser.add_argument("--marker-margin", required=True, type=float, help="Margin around the Aruco marker in cm (From protocol)")
    parser.add_argument("--fps", type=int, default=30, help="Frames per second for video processing (default: 30)")
    parser.add_argument("--display", action="store_true", default=False, help="If true will display tracker on video")
    parser.add_argument("--cube", action="store_true", help="If provided will use cube to detect table grund")
    parser.add_argument("--no-cube", action="store_true", help="If provided will NOT use cube to detect table grund")
    parser.add_argument("--dobot", action="store_true", help="Argument need to be provided if dobot is used during recordings")
    parser.add_argument("--no-dobot", action="store_true", help="Argument need to be provided if dobot is NOT used during recordings")
    parser.add_argument("--needle-offset", required=True, type=float, help="Needle offset in cm (From protocol)")
    parser.add_argument("--z-offset", type=float, help="Z-axis offset in cm, if not provided default offset will be used")
    parser.add_argument("--starting-position", default=0.0, type=float, help="Starting position of the needle in cm (default: 0.0 cm). Used only by mode without cube")
    parser.add_argument("--table-offset", default=0.0, type=float,
                         help="E.g. when provided 2cm, level 0 will be 2 cm above table (By default 0.0 cm)")
    parser.add_argument("--distances-path", type=str, help="Path to distances.txt file for annotations (if not provided, will not annotate, only track positions)")
    parser.add_argument("--annotation-axis", type=str.upper, choices=["X", "Y", "Z"], default="Y", help="Coordinate used for annotations (default: Y).")
    return parser.parse_args()

def main():
    global ANNOTATION_AXIS

    args = parse_args()
    ANNOTATION_AXIS = args.annotation_axis

    root_dir = args.root_dir
    if not root_dir.is_dir():
        print(f"Folder {root_dir} not found.")
        return

    if not args.cube and not args.no_cube:
        print("Please you have to specify either --cube or --no-cube.")
        return

    if args.cube and args.no_cube:
        print("You cannot specify both --cube and --no-cube.")
        return

    if not args.dobot and not args.no_dobot:
        print("Please you have to specify either --dobot or --no-dobot.")
        return

    if args.dobot and args.no_dobot:
        print("You cannot specify both --dobot and --no-dobot.")
        return

    display = args.display
    if(args.cube):
        print("Running in cube mode.")
        cube_mode = True
    elif(args.no_cube):
        print("Running in no-cube mode.")
        cube_mode = False

    if(args.dobot):
        print("Tracking for dobot.")
        dobot_mode = True
    elif(args.no_dobot):
        print("Tracking for manual.")
        dobot_mode = False

    marker_length_obj = args.marker_length
    marker_margin_obj = args.marker_margin
    fps = args.fps
    needle_offset = args.needle_offset
    starting_position = args.starting_position
    z_offset = args.z_offset
    table_offset = args.table_offset
    distances_path = args.distances_path

    run_aruco_tracking_for_folder(
        root_dir,
        args.camera,
        cube_mode,
        dobot_mode,
        marker_length_obj,
        marker_margin_obj,
        needle_offset,
        starting_position=starting_position,
        z_offset=z_offset,
        table_offset=table_offset,
        fps=fps,
        distances_path=distances_path,
        display=display
    )

if __name__ == "__main__":
    main()

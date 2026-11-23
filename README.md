# UltraClear Acquisition

Web application for synchronized acquisition of:

- one or two cameras with an optional shared audio input,
- an optional MEMS microphone connected to a Raspberry Pi,
- an ultrasound scanner,
- IMU and PSMove trackers,
- Dobot robot positions.

Devices are connected only after enabling their checkbox in the application.

## Installation

Requires Python 3.10 and FFmpeg 4.3.1. To install the tool:

1. Create a folder for the tool and enter it.
2. Open a command line in this folder and create a virtual environment:

```commandline
python -m venv .acq
```

3. Activate the environment.

On Windows, it may first be necessary to run:

```commandline
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate the environment:

```commandline
.acq/Scripts/Activate.ps1
```

On Linux:

```commandline
source .acq/bin/activate
```

4. Install the tool:

```commandline
python -m pip install https://github.com/UltraclearRepos/acquisition_ultraclear/archive/main.zip
```

To install a specific version:

```commandline
python -m pip install https://github.com/UltraclearRepos/acquisition_ultraclear/archive/refs/tags/<version>.zip
```

To run the application later, open a terminal in the tool folder and activate
the environment as described above.

## Device setup

The ultrasound scanner and PSMove tracker need vendor software. Install it only
for the devices you plan to use.

### Ultrasound scanner (Telemed)

1. **Telemed drivers and Echo Wave II.** Download and install both packages from
   the [Telemed software page](https://www.pcultrasound.com/support/software/).
2. **USGFW2 SDK.** Download the SDK from the
   [Telemed SDK page](https://www.pcultrasound.com/support/sdk/), extract it
   with the password `7e39k47g893dpk`, and complete the installation.
3. **Research tools.** Download the *TELEMED Real-time Imaging for the Research*
   ZIP package from the
   [Telemed research tools page](https://www.pcultrasound.com/research/research_tools/)
   and extract it.
4. **Configuration.** Set `usg_dll_path` in `setup.json` to `usgfw2wrapper.dll`
   from the research tools package, for example
   `...\Real-time Imaging for the Research\usgfw2wrapper_C++_sources\x64\Release\usgfw2wrapper.dll`.

> **Warning:** Extract the Telemed ZIP files with WinRAR or 7-Zip. The default
> Windows unzip tool can corrupt the files.

### PSMove tracker (PSMoveServiceEx)

1. **Download.** Download the `.zip` file of the latest
   [PSMoveServiceEx release](https://github.com/Timocop/PSMoveServiceEx/releases)
   and extract it to a local folder.
2. **PSEye cameras.** When setting up PlayStation Eye cameras for the first
   time, install their drivers according to the
   [PSEye setup instructions](https://github.com/psmoveservice/PSMoveService/wiki/PSEye-Software-Setup-(Windows)).
3. **Controller pairing.** Pair the PS Move controllers via Bluetooth according
   to the
   [pairing instructions](https://github.com/psmoveservice/PSMoveService/wiki/PSMove-Bluetooth-Pairing).
   The first pairing requires a USB connection.
4. **Calibration.** Run `PSMoveService.exe` and then `PSMoveConfigTool.exe` from
   the extracted folder, and complete the calibrations in this order:
   1. [Magnetometer](https://github.com/psmoveservice/PSMoveService/wiki/PSMove-Magnetometer-Calibration),
   2. [Color filter](https://github.com/psmoveservice/PSMoveService/wiki/Color-Filter-Calibration),
   3. [Tracker pose](https://github.com/psmoveservice/PSMoveService/wiki/Tracker-Pose-Calibration).
5. **Configuration.** Set `psmove_dll_path` in `setup.json` to
   `PSMoveClient_CAPI.dll` from the extracted PSMoveServiceEx folder.

`PSMoveService.exe` must be running before the `PSMove Tracker` checkbox is
enabled in the application.

## Configuration

All configuration is stored in one `setup.json` file:

```json
{
  "usg_dll_path": "C:\\path\\to\\usgfw2wrapper.dll",
  "psmove_dll_path": "C:\\path\\to\\PSMoveClient_CAPI.dll",
  "imu_port": "COM11",
  "raspberry_pi": {
    "host": "raspberrypi.local",
    "port": 22,
    "username": "pi",
    "password": ""
  },
  "remote_dir": "uclr_acquisition",
  "grid_config": "C:\\path\\to\\grid_config.json",
  "materials": ["Slime", "Silicone", "PU"],
  "needleTypes": ["Type1", "Type2", "Type3"],
  "sensorVersions": ["TypeA", "TypeB", "TypeC"]
}
```

Fields are read only when the feature that uses them is enabled, so the fields
of unused devices can be omitted:

| Field | Required for |
|---|---|
| `usg_dll_path` | `USG Scanner` checkbox |
| `psmove_dll_path` | `PSMove Tracker` checkbox |
| `imu_port` | `IMU Tracker` checkbox |
| `raspberry_pi`, `remote_dir` | `Raspberry Pi MEMS microphone` checkbox |
| `grid_config` | `Grid (from file)` automation mode |
| `materials`, `needleTypes`, `sensorVersions` | options of the `Material`, `Needle type`, and `Sensor version` selects |

An empty Raspberry Pi password allows key-based or SSH-agent authentication.
MEMS WAV files are always downloaded to `audio_raw/` in the working directory.

`MEMS recorded channels` in the Devices section selects the WAV channels:

- `2 (stereo)` records both I2S channels with the `dmic_sv_shared` ALSA device,
- `1 (left only)` records only the left channel with the
  `dmic_sv_shared_1channel` ALSA device.

Both devices are defined in `uclr_acquisition/sensors/asoundrc.txt`, which is
uploaded to `/home/pi/.asoundrc` when the MEMS checkbox is enabled. A mono WAV
has only channel 0, so use `--audio-channel 0` with `uclr_sync`,
`uclr_annotate`, and `uclr_review_annotations`.

The selected material, needle type, and sensor version are added to recording
file names. A missing list leaves its select empty.

## uclr_acquisition

```commandline
usage: uclr_acquisition [-h] [--setup SETUP] [--port PORT]

Web browser interface for synchronous acquisition of audio (from rasberry_pi/banana_pi devboard)
and video from webcam

options:
  -h, --help     show this help message and exit
  --setup SETUP  Path to setup JSON file (if not provided or some fields are missing, default
                 configuration is used.)
  --port PORT    Port (default 5000)
```

Run in commandline:

```commandline
uclr_acquisition --setup setup.json
```

This runs the application in Python and opens the web interface in the browser
at `http://127.0.0.1:5000`, or at the port passed with `--port`. Stop the
application with Ctrl+C in the commandline.

Run the command in the folder where recordings should be saved. Without
`--setup`, the features listed in [Configuration](#configuration) cannot read
their settings.

Camera recordings are saved as `video_cam1/<recording>.webm` and
`video_cam2/<recording>.webm`. Both cameras use the same file name, without a
camera suffix. MEMS WAV files are saved as `audio_raw/<recording>.wav`.

## uclr_sync

```commandline
usage: uclr_sync [-h] [--root-dir ROOT_DIR] --audio-channel AUDIO_CHANNEL

Synchronize sensor data timestamps and Raspberry Pi MEMS audio with camera recordings.

options:
  -h, --help            show this help message and exit
  --root-dir ROOT_DIR   Directory containing video_cam1/, video_cam2/, audio_raw/ and sensor data
                        folders (default: current directory).
  --audio-channel AUDIO_CHANNEL
                        Audio channel to use for synchronization
```

Run in commandline from the folder where `uclr_acquisition` saved the
recordings:

```commandline
uclr_sync --audio-channel 0
```

or pass that folder explicitly:

```commandline
uclr_sync --root-dir D:\path\to\recordings --audio-channel 0
```

For every recording in `video_cam1/` and `video_cam2/`, the command:

1. adds or updates the `sync_timestamp` column in the matching CSV files in
   `dobot/`, `usg_timestamps/`, `imu/`, and `psmove/`,
2. shifts the audio stream of every camera WebM file so it starts together
   with the video stream, without re-encoding. Offsets below 10 ms are ignored,
3. finds the synchronization chirp in the `cam1` audio and in the matching WAV
   file in `audio_raw/`, and cuts the WAV so it starts and ends together with
   the `cam1` video. When the `cam1` recording has no audio, `cam2` is used.

When the WAV starts after the video or ends before it, that part of the WAV is
left unchanged. The WAV samples are only cut, without re-encoding or
resampling.

The device delays are defined at the top of `uclr_acquisition/synchronize.py`
as `delay = device_time - camera_time`, and
`sync_timestamp = timestamp - delay`. USG MP4 files are not modified.

The command modifies CSV, WebM, and WAV files in place, so keep a copy of the
original recordings when they are needed. FFmpeg and `ffprobe` must be
available on `PATH`.

## uclr_annotate

```commandline
usage: uclr_annotate [-h] [--camera {cam1,cam2}] --audio-channel {0,1}

Annotate acquisition videos from the video_cam1/ or video_cam2/ directory and use matching audio
from the audio_raw/ directory.

options:
  -h, --help            show this help message and exit
  --camera {cam1,cam2}  Camera recordings to annotate (default: cam1).
  --audio-channel {0,1}
                        Audio channel used for playback and visualization.
```

Run in commandline from the folder where `uclr_acquisition` saved the
recordings:

```commandline
uclr_annotate --camera cam2 --audio-channel 1
```

Videos are read from `video_cam1/`, or `video_cam2/` with `--camera cam2`, and
the matching WAV files from `audio_raw/`. Annotations are saved in
`annotations/<recording>.json`, shared by both cameras.

| Key | Action |
|---|---|
| 1-8 | Mark event at the current frame. Events must be marked in order, and marking an event removes the later ones. |
| Ctrl + 1-8 | Restore the event saved earlier for the recording. |
| Space | Pause or resume. |
| A / D | Previous or next frame while paused. |
| N / P | Next or previous recording. |
| C | Clear new events. |
| R | Reset zoom. |
| Esc | Exit. |

Waveform and spectrogram views can be selected from the control bar.

## uclr_annotate_positions

```commandline
usage: uclr_annotate_positions [-h] [--root-dir ROOT_DIR] [--camera {cam1,cam2}] --marker-length
                               MARKER_LENGTH --marker-margin MARKER_MARGIN [--fps FPS] [--display]
                               [--cube] [--no-cube] [--dobot] [--no-dobot] --needle-offset
                               NEEDLE_OFFSET [--z-offset Z_OFFSET]
                               [--starting-position STARTING_POSITION]
                               [--table-offset TABLE_OFFSET] [--distances-path DISTANCES_PATH]
                               [--annotation-axis {X,Y,Z}]

Tool for annotating position of needle in videos from the video_cam1/ or video_cam2/ folder.
Matching audio files are read from the audio_raw/ folder. Positions are saved in the
labelled_positions/ folder. When you provide distances.txt file, it will produce annotations in
the annotations/ folder. distances.txt file should look like: 12,8.5,7,5.4

options:
  -h, --help            show this help message and exit
  --root-dir ROOT_DIR   Directory containing video_cam1/, video_cam2/ and audio_raw/ folders
                        (default: current directory).
  --camera {cam1,cam2}  Camera recordings to track (default: cam1).
  --marker-length MARKER_LENGTH
                        Length of the Aruco marker in cm (From protocol)
  --marker-margin MARKER_MARGIN
                        Margin around the Aruco marker in cm (From protocol)
  --fps FPS             Frames per second for video processing (default: 30)
  --display             If true will display tracker on video
  --cube                If provided will use cube to detect table grund
  --no-cube             If provided will NOT use cube to detect table grund
  --dobot               Argument need to be provided if dobot is used during recordings
  --no-dobot            Argument need to be provided if dobot is NOT used during recordings
  --needle-offset NEEDLE_OFFSET
                        Needle offset in cm (From protocol)
  --z-offset Z_OFFSET   Z-axis offset in cm, if not provided default offset will be used
  --starting-position STARTING_POSITION
                        Starting position of the needle in cm (default: 0.0 cm). Used only by mode
                        without cube
  --table-offset TABLE_OFFSET
                        E.g. when provided 2cm, level 0 will be 2 cm above table (By default 0.0
                        cm)
  --distances-path DISTANCES_PATH
                        Path to distances.txt file for annotations (if not provided, will not
                        annotate, only track positions)
  --annotation-axis {X,Y,Z}
                        Coordinate used for annotations (default: Y).
```

Run in commandline from the folder where `uclr_acquisition` saved the
recordings, or pass that folder with `--root-dir`:

```commandline
uclr_annotate_positions --marker-length 4 --marker-margin 0.5 --needle-offset 3 --no-cube --dobot --fps 15 --distances-path distances.txt
```

The command tracks ArUco marker 0 (`DICT_4X4_50`) in every recording in
`video_cam1/`, or in `video_cam2/` with `--camera cam2`. The cube mode
additionally requires the `DICT_5X5_100` cube markers 0-2 in the first frames.

Outputs in the root directory:

- `labelled_positions/<recording>.csv` - needle position and velocity in every
  frame,
- `annotations/<recording>.json` - frames where the needle crosses the
  distances from `distances.txt`. Audio annotations are added when the
  matching WAV in `audio_raw/` has the same duration as the video
  (±0.1 s).

Pass `--fps` equal to the recording frame rate: 15 for the `Better quality`
video profile and 30 for `Better performance`. Frame times and audio samples
are calculated from it.

The output files are overwritten when the command runs again, also for the
other camera. `annotations/<recording>.json` is the same file that
`uclr_annotate` uses.

## uclr_review_annotations

```commandline
usage: uclr_review_annotations [-h] [--root-dir ROOT_DIR] --audio-channel AUDIO_CHANNEL

Browse annotated video frames and needle positions. Videos are read from video_cam1/, WAV files
from audio_raw/, annotations from annotations/ and positions from labelled_positions/.

options:
  -h, --help            show this help message and exit
  --root-dir ROOT_DIR   Directory containing video_cam1/, video_cam2/, audio_raw/, annotations/
                        and labelled_positions/ folders (default: current directory).
  --audio-channel AUDIO_CHANNEL
                        WAV channel for the spectrogram
```

Run in commandline from the folder where `uclr_acquisition` saved the
recordings, or pass that folder with `--root-dir`:

```commandline
uclr_review_annotations --audio-channel 0
```

The viewer shows every annotated frame of the `video_cam1/` recordings that
have both `annotations/<recording>.json` and
`labelled_positions/<recording>.csv`, together with the needle position and
the spectrogram of `audio_raw/<recording>.wav`. Navigation spans all
recordings and starts paused.

| Key | Action |
|---|---|
| Space | Play or pause, one annotation per second. |
| A / D | Previous or next annotation. |
| Left / Right | Step one frame from the annotation (blue marker). |
| Enter | Save the stepped frame as the annotation (green marker), also updating the audio annotation. |
| F | Copy the `cam1` and `cam2` videos and the WAV of the current recording to `tofix_video_cam1/`, `tofix_video_cam2/`, and `tofix_audio_raw/`. Missing files are skipped. |
| Esc | Exit. |


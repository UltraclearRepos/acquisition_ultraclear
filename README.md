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
  "local_dir": "micro_data",
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
| `local_dir` | MEMS WAV download folder, `Delete Last Recording`, and `uclr_annotate` |
| `grid_config` | `Grid (from file)` automation mode |
| `materials`, `needleTypes`, `sensorVersions` | options of the `Material`, `Needle type`, and `Sensor version` selects |

An empty Raspberry Pi password allows key-based or SSH-agent authentication.
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

## uclr_sync

Synchronizes sensor data and Raspberry Pi MEMS audio with camera recordings.
The command has no options and no help message: running `uclr_sync --help`
also starts the synchronization.

Run in commandline from the folder where `uclr_acquisition` saved the
recordings:

```commandline
uclr_sync
```

For every recording in `videos/`, the command:

1. adds or updates the `sync_timestamp` column in the matching CSV files in
   `dobot/`, `usg_timestamps/`, `imu/`, and `psmove/`,
2. shifts the audio stream of every camera WebM file so it starts together
   with the video stream, without re-encoding. Offsets below 10 ms are ignored,
3. finds the synchronization chirp in the `cam1` audio and in the matching WAV
   file in `micro_data/`, and cuts the WAV so it starts and ends together with
   the `cam1` video.

When the WAV starts after the video or ends before it, that part of the WAV is
left unchanged. The WAV samples are only cut, without re-encoding or
resampling.

The device delays are defined at the top of `uclr_acquisition/synchronize.py`
as `delay = device_time - camera_time`, and
`sync_timestamp = timestamp - delay`. WAV files are read from `micro_data/`
regardless of `local_dir`. USG MP4 files are not modified.

The command modifies CSV, WebM, and WAV files in place, so keep a copy of the
original recordings when they are needed. FFmpeg and `ffprobe` must be
available on `PATH`.

## uclr_annotate

```commandline
usage: uclr_annotate [-h] [--camera {cam1,cam2}] [--audio-channel {0,1}]

Annotate acquisition videos from the videos/ directory and use matching audio from local_dir
configured in setup.json.

options:
  -h, --help            show this help message and exit
  --camera {cam1,cam2}  Camera recordings to annotate (default: cam1).
  --audio-channel {0,1}
                        Audio channel used for playback and visualization (default: 0).
```

Run in commandline from the folder where `uclr_acquisition` saved the
recordings:

```commandline
uclr_annotate --camera cam2 --audio-channel 1
```

Videos are read from `videos/`. The matching WAV file is read from `local_dir`
in `setup.json` in the same folder, or from `micro_data/` when the setting is
missing. Annotations are saved in `annotations/<recording name>.json`.

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


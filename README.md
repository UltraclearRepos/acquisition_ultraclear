# UltraClear Acquisition

Web application for synchronized acquisition of:

- one or two cameras with an optional shared audio input,
- an optional MEMS microphone connected to a Raspberry Pi,
- an ultrasound scanner,
- IMU and PSMove trackers,
- Dobot robot positions.

Devices are connected only after enabling their checkbox in the application.

## Installation

### Highly recommended installation

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

### Basic installation (not recommended)

```commandline
python -m pip install https://github.com/UltraclearRepos/acquisition_ultraclear/archive/main.zip
```

The ultrasound scanner and PSMove require their vendor DLLs. Raspberry Pi
recording requires SSH access and an ALSA-compatible MEMS microphone.

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
  "remote_dir": "uclr_acquisition"
}
```

An empty Raspberry Pi password allows key-based or SSH-agent authentication.

## Running

Start the application with:

```powershell
uclr_acquisition --setup setup.json
```

To use a different HTTP port:

```powershell
uclr_acquisition --setup setup.json --port 5001
```

The application opens the browser automatically. The default address is
`http://127.0.0.1:5000`.

## Recording workflow

1. Enable the required USG, tracker, or Raspberry Pi MEMS devices.
2. Select one or two camera sources.
3. Select `Camera audio input source` to embed audio in the camera recordings.
   Selecting `None` records video without an audio track.
4. Configure the Dobot path and start automation, or switch to manual mode.

Both camera recordings use the same browser audio track. Audio is embedded
directly in each WebM file and is not saved as a separate camera-audio file.

When the Raspberry Pi MEMS microphone is enabled, it records a stereo,
48 kHz, 32-bit WAV using `arecord`. The WAV is downloaded to `local_dir`
after recording.

After the MEMS recorder and camera start, the application plays the same
0.2-second, 500-4000 Hz chirp used by VibroNav through the system default
audio output. The chirp is a marker for aligning camera audio and the
Raspberry Pi WAV during post-processing.

## Output files

Depending on the enabled devices, recordings are stored in:

- `videos/` - camera WebM files,
- `video_timestamps/` - camera start timestamps,
- `micro_data/` or the configured `local_dir` - Raspberry Pi MEMS WAV files,
- `usg/` and `usg_timestamps/` - ultrasound recordings,
- `dobot/` - Dobot positions,
- `imu/` and `psmove/` - tracker data.

`Delete Last Recording` removes files belonging to the most recent recording
from the local output directories.

## Synchronization

The package installs a separate synchronization command:

```powershell
uclr_sync
```

Run it from the acquisition directory containing `videos/`, `micro_data/`,
`dobot/`, `usg_timestamps/`, `imu/`, and `psmove/`. It can also be started
without the console entry point:

```powershell
python -m uclr_acquisition.synchronize
```

The synchronization delays are defined at the top of
`uclr_acquisition/synchronize.py`. Every device uses the same convention:

```text
delay = device_time - camera_time
sync_timestamp = timestamp - delay
```

For each camera recording, the script finds data files with the same recording
name and adds or updates their `sync_timestamp` column. It processes Dobot,
USG timestamp, IMU, and PSMove CSV files. Both `timestamp` and `Timestamp`
column names are supported.

For a matching Raspberry Pi WAV, the script:

1. extracts the embedded camera audio with FFmpeg,
2. finds the synchronization chirp in both audio streams,
3. calculates the difference between the chirp positions,
4. removes the corresponding beginning of the WAV when the MEMS chirp occurs
   later than the camera chirp.

Camera WebM files and USG MP4 files are not trimmed. If no camera audio stream
or synchronization chirp is found, the WAV remains unchanged.

The script modifies matching CSV and WAV files in place. Keep a copy of the
original recordings when the unmodified data is required. FFmpeg and
`ffprobe` must be available on `PATH`.

## Video annotation

The package installs a separate annotation command. Run it from the acquisition
directory containing `videos/`, `setup.json`, and the configured `local_dir`:

```powershell
uclr_annotate
```

The command annotates `cam1` recordings by default. To annotate the second
camera instead, run:

```powershell
uclr_annotate --camera cam2
```

Select audio channel `0` or `1` with:

```powershell
uclr_annotate --camera cam2 --audio-channel 1
```

Video paths are read automatically from `videos/`. Matching WAV files are read
from `local_dir` in `setup.json`, falling back to `micro_data/` when no setting
is available. Camera suffixes (`_cam1` and `_cam2`) are removed when matching a
video to its WAV file. Annotation JSON files are saved in `annotations/`.

The annotation window supports events 1-8, Space to pause or resume, A/D to
move between frames while paused, N/P to move between recordings, C to clear
new events, R to reset zoom, and Escape to exit. Waveform and spectrogram views
can be selected from the control bar. The selected audio channel is used for
visualization and playback. The tool does not read labelled-position files and
does not display a velocity plot.

## Raspberry Pi MEMS requirements

The application uploads the bundled ALSA configuration to the Raspberry Pi
when the MEMS checkbox is enabled. The default recording device is
`dmic_sv_shared`.

The Raspberry Pi must provide:

- SSH connectivity from the acquisition computer,
- the `arecord` command,
- an I2S MEMS microphone exposed as `dmic_sv_shared`,
- write access to the configured `remote_dir`.

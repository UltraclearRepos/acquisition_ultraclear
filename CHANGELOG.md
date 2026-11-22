# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2026-11-23
### Added
- MEMS recorded channels selection: 2 channels (stereo) or 1 channel (left only)

### Changed
- `uclr_sync` and `uclr_review_annotations` report a clear message when the selected audio channel is not in the WAV file

## [1.1.0] - 2026-11-18
### Added
- `uclr_annotate_positions` command for ArUco needle position tracking and distance annotations
- `uclr_review_annotations` command for browsing and correcting annotations with needle positions

### Changed
- MEMS WAV files are always stored in `audio_raw/`, the `local_dir` setup field is removed
- Camera recordings are stored in `video_cam1/` and `video_cam2/` instead of `videos/`, without the `_cam1`/`_cam2` file name suffix
- `--audio-channel` is required in `uclr_annotate` instead of defaulting to channel 0

## [1.0.0] - 2026-11-18
### Added
- Up/Down dobot mode
- Grid (from file) dobot mode
- Video recording profile selection: better quality (VP9) or better performance (H.264)
- Material, needle type and sensor version selects with options from setup.json, added to recording file names

### Changed
- Remux H.264 camera recordings with the Matroska muxer
- Rename Dobot movement type to automation mode
- Rename coordinate path automation endpoint from `/run` to `/run-points`
- Synchronization shifts the camera audio stream to start with the video stream
- Synchronization cuts the end of the MEMS WAV to the camera video duration

## [0.8.0] - 2026-09-30
### Added
- Camera upload completion signaling between the browser and backend
- Background WebM remuxing to finalize recording duration and container metadata

### Changed
- Request and validate an exact camera frame rate of 15 FPS
- Wait for all enabled camera recordings to be saved before completing `stop_recording`
- Disable a camera and notify the user when its stream cannot be configured correctly

## [0.7.0] - 2026-09-01
### Added
- arc movement dobot mode

## [0.6.0] - 2026-08-12
### Added
- Annotation tool for audio based on video


## [0.5.0] - 2026-07-25
### Added
- Optional Raspberry Pi MEMS WAV recording controlled from the Devices section
- Camera/MEMS synchronization using the VibroNav chirp
- Synchronization tool
### Changed
- Camera audio source changes now restart both camera streams


## [0.4.2] - 2026-05-19
### Fixed
- Fix collecting data from IMU buffer

## [0.4.1] - 2025-05-05
### Changed
- Enable recording with multiple trackers
- Remove microphone output device selection

## [0.4.0] - 2026-05-04
### Added
- PSMove tracker
- Selecting tracker to use

## [0.3.0] - 2026-04-26
### Added
- Live resolution display for cameras
- Enable recording only with 1 camera
### Changed
- Video format for cam1 from 1920x1080 to 640x360
### Fixed
- Timeout error when using two cameras at once
- Closing terminal with tool not closing streams properly

## [0.2.0] - 2026-04-22
### Added
- Usg scanner control
- Usg scanner live feed
- Usg scanner recording
- Dobot logging
- Dobot control
- Cameras recording
- Cameras live feed
- IMU logging

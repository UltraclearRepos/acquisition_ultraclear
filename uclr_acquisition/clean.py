import argparse
from scipy.io import wavfile
from scipy.signal import filtfilt, medfilt
import os
import numpy as np
import glob
import tqdm


def read_wave(path):
    sample_rate, x = wavfile.read(path)
    x = x.T
    if x.dtype == np.int32:
        x = x / float(2**31-1)
    elif x.dtype == np.int16:
        x = x / float(2**15-1)
    if len(x.shape) == 1:
        x = x[None, :]
    return sample_rate, x


def highpass(x: np.ndarray, offset_samples: int = 0, filter_order=200):
    h = np.ones(filter_order)/filter_order
    h = np.convolve(np.convolve(h, h), h)
    x = x[offset_samples:]
    y = x - filtfilt(h, 1, x)
    return y


CLOSE = 8
LOW_TH = 0.05
HI_TH = 0.2


def remove_peaks(x, close=CLOSE, low_th=LOW_TH, hi_th=HI_TH):
    y = x.copy()
    peaks = np.where(np.abs(y) > hi_th)[0]

    filtered_peaks = []
    for peak in peaks:
        if not filtered_peaks or peak - filtered_peaks[-1] > close:
            filtered_peaks.append(peak)
    for peak in filtered_peaks:
        y_context = y[max(peak - 2 * close, 0):min(peak + 3 * close, len(y) - 1)]
        median = np.median(y_context)
        start, end = max(peak - close // 2, 0), min(peak + close, len(y) - 1)
        y_clip = y[start:end]
        y_clip[np.abs(y_clip - median) > low_th] = median
        y[start:end] = y_clip
    return y


def remove_spikes(x, low_th=LOW_TH, median_len=11):
    y = x.copy()
    y_median = medfilt(y, median_len)
    y_no_dc = y - y_median
    y_neighbours = np.vstack((y_no_dc[:-2], y_no_dc[2:]))
    spikes = np.where(np.abs(y_no_dc[1:-1])*low_th > np.abs(y_neighbours).max(axis=0))[0]
    y[spikes + 1] = y_median[spikes+1]
    return y


def normalize(x):
    return x/np.max(np.abs(x))


def write_wave(path, sample_rate, data, dtype=np.int32):
    if dtype == np.int32:
        data = (data * (2 ** 31 - 1)).astype(dtype)
    elif dtype == np.int16:
        data = (data * (2 ** 15 - 1)).astype(dtype)
    wavfile.write(path, sample_rate, data)


def clean_wav(input_file: str, output_path: str, offset: float, wave_word_size=16, clean_spikes=False):
    fs, x = read_wave(input_file)
    x_clean = []
    for x_channel in x:
        x_declipped = remove_spikes(remove_peaks(x_channel)) if clean_spikes else x_channel
        x_nodc = highpass(x_declipped, int(offset*fs))
        x_clean.append(normalize(x_nodc))
    x_clean = np.array(x_clean).T
    output_file = os.path.join(output_path, os.path.basename(input_file)[:-len(".wav")] + ".processed.wav")
    output_file = output_file.replace(".raw.processed.wav", ".processed.wav")
    write_wave(output_file, fs, x_clean, {16: np.int16, 32: np.int32}[wave_word_size])
    return [output_file, input_file]


def main():
    parser = argparse.ArgumentParser(description="Read, clean and save WAV file(s).")
    parser.add_argument("--input-file", type=str, default="", required=False,
                        help="Single input WAV file to process.")
    parser.add_argument("--input-path", type=str, default="", required=False,
                        help="Path with WAV files file to process.")
    parser.add_argument("--spikes", type=bool, default=False, required=False,
                        help="Removes spikes.")
    parser.add_argument("--offset", type=float, default=0.02, required=False,
                        help="Time offset to skip at the beginning of waveform.")
    parser.add_argument("--wave-word-size", type=int, default=16, required=False,
                        help="Size of word (16 or 32 bits) for saving WAV file.")
    parser.add_argument("--output-path", type=str, default="", required=False,
                        help='Target directory (if not provided, files will be saved on input path '
                             'with "processed" suffix).')

    args = parser.parse_args()

    if args.output_path:
        os.makedirs(args.output_path, exist_ok=True)
    if args.input_path:
        input_files = glob.glob(os.path.join(args.input_path, "*.wav"))
        if not args.output_path:
            args.output_path = args.input_path
    elif args.input_file:
        input_files = [args.input_file]
        if not args.output_path:
            args.output_path = os.path.dirname(args.input_file)
    else:
        input_files = []

    fails = []
    for input_file in tqdm.tqdm(input_files):
        try:
            clean_wav(input_file, args.output_path, args.offset, args.wave_word_size, args.spikes)
        except:
            fails.append(input_file)
    for fail in fails:
        print("Failed:", fail)


if __name__ == "__main__":
    main()

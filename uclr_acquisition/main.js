'use strict';

/* globals MediaRecorder */
// Spec is at http://dvcs.w3.org/hg/dap/raw-file/tip/media-stream-capture/RecordingProposal.html


const usernameEl = document.getElementById('username');
const iterEl = document.getElementById("iterations");
const descriptionEl = document.getElementById("description");
const startAutomationBt = document.getElementById("startTests");
const stopAutomationBt = document.getElementById("stopTests");
const startRecordingBt = document.getElementById("startRecording");
const stopRecordingBt = document.getElementById("stopRecording");
const raspberryStatusEl = document.getElementById("raspberryStatus");
const automationStatusEl = document.getElementById("automationStatus");
const iterationCounterEl = document.getElementById("iterationCounter");
const recordingDurationEl = document.getElementById("recordingDuration");
const deleteRecordingBt = document.getElementById("deleteRecording");
const toggleDataStreamBt = document.getElementById("toggleDataStream");


const materialsContainter = document.getElementById("material");
const speedSlider = document.getElementById("speed");
const speedValueEl = document.getElementById("speedValue");
const needleTypeContainer = document.getElementById("needleType");
const sensorVersionContainer = document.getElementById("sensorVersion");
const timerEl = document.getElementById("recordingTimer");

const audioInputSelect = document.getElementById("audioSource");
const microOutputSelect = document.getElementById("microOutput");
const videoSelect = document.getElementById("videoSource");
const videoSelect2 = document.getElementById("videoSource2");
const selectors = [audioInputSelect, videoSelect, videoSelect2];

const liveVideoElement = document.getElementById('video');
const liveVideoElement2 = document.getElementById('video2');

liveVideoElement.controls = false;
liveVideoElement2.controls = false;

let localStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let localStream2 = null;
let mediaRecorder2 = null;
let recordedChunks2 = [];
let shouldUpload = true;
let recordingStartTime = null;
let recordingTimerInterval = null;
let sharedAudioTrack = null;

const spectrogram = document.getElementById('spectrogram');
const ctx = spectrogram.getContext('2d');

const interval = 300;
const sampleRate = 48000;
const fftSize = 4096;
const fft = new FFT(fftSize, sampleRate);
let specBuffer = []

let isCtrlZoomingWaveform = false;
let lastYWaveform = null;
let isPanningWaveform = false;
let waveformZoom = 1;
let waveformOffset = 0;
let singalLeftHistory = [];
let signalRightHistory = [];
const waveformCanvasLeft = document.getElementById('micSignalLeft');
const waveformCanvasRight = document.getElementById('micSignalRight');
const waveformCtxLeft = waveformCanvasLeft.getContext('2d');
const waveformCtxRight = waveformCanvasRight.getContext('2d');

const specCenterFreqEl = document.getElementById("specCenterFreq");
const specZoomEl = document.getElementById("specZoom");
const applySpecScaleBt = document.getElementById("applySpecScale");

let specZoom = 1;
let specOffset = 0;
let isCtrlZoomingSpec = false;
let isPanningSpec = false;
let lastYSpec = null;
let specHistory = [];

const toggle = document.getElementById("modeToggle");
const automationForm = document.getElementById("automationForm");
const manualForm = document.getElementById("manualForm");
const intervalToggle = document.getElementById("intervalToggle");
const intervalEL = document.getElementById("interval");
const sleepTimeEl = document.getElementById("sleepTime");

const detectCubeBt = document.getElementById("detectCube");
const cubeModal = document.getElementById("cubeModal");
const cubeModalImage = document.getElementById("cubeModalImage");
const cubeModalClose = document.getElementById("cubeModalClose");

const filterToggle = document.getElementById("filterToggle");
const filterFields = document.querySelector(".filter-fields");
const bpLowEl = document.getElementById("bpLow");
const bpHighEl = document.getElementById("bpHigh");
const applyFilterBt = document.getElementById("applyFilter");

const DEFAULT_CONFIG = {
	materials: ["slime", "Silicone", "Chicken"],
	speeds: ["slow", "medium", "fast"]
};
const YAXIS_SPECTROGRAM_WIDTH = 55;
const YAXIS_WAVEFORM_WIDTH = 75;

const socket = io();
socket.on("connect", () => {
	console.log("Socket.io connected from browser")
})

socket.on("record", async (msg) => {

	const action = msg.action;
	const filename = msg.filename;
	console.log(action);

	if (!localStream || !localStream2) {
		console.warn("No media stream available to record");
		return;
	}

	if (action === "start") {

		onRecordStart({
			filename: addSuffix(filename, "_cam1"),
			stream: localStream,
			setRecorder: (recorder) => mediaRecorder = recorder,
			setChunks: (chunks) => recordedChunks = chunks,
		});
		onRecordStart({
			filename: addSuffix(filename, "_cam2"),
			stream: localStream2,
			setRecorder: (recorder) => mediaRecorder2 = recorder,
			setChunks: (chunks) => recordedChunks2 = chunks,
		});
		console.log("Browser started recording");

		startSimultaneously(
			() => mediaRecorder.start(),
			() => mediaRecorder2.start()
		)

	}

	console.log(mediaRecorder, mediaRecorder2);
	if (action === "stop" && mediaRecorder && mediaRecorder.state === "recording" && mediaRecorder2 && mediaRecorder2.state === "recording") {
		shouldUpload = msg.shouldUpload;
		if (!shouldUpload) {
			alert("Recording is not saved!")
		}
		mediaRecorder.requestData();
		mediaRecorder2.requestData();
		Promise.resolve().then(() => {
			mediaRecorder.stop();
			mediaRecorder2.stop();
			console.log("Browser stopped recording");
		})
	}

});

socket.on("automation-status", (msg) => {
	const status = msg.status;
	automationStatusEl.textContent = `Automation status: ${status}`;
	automationStatusEl.style.color = status === "running" ? "green" : "red";
	if (status === "running") {
		toggleButtons(true);
		startRecordingTimer();
		stopRecordingBt.disabled = true;
	} else {
		toggleButtons(false);
		stopRecordingTimer();
		iterationCounterEl.textContent = `Iteration: -`
	}
});

socket.on("iteration", (msg) => {
	const iterInput = iterEl.value;
	const maxIterations = iterInput ? parseInt(iterInput, 10) || 1 : 1
	const currentIteration = msg.iteration;
	iterationCounterEl.textContent = `Iteration: ${currentIteration} / ${maxIterations}`;
});

function fastMinMax(arr) {
	let min = arr[0], max = arr[0];
	for (let i = 1; i < arr.length; i++) {
		if (arr[i] < min) min = arr[i];
		if (arr[i] > max) max = arr[i];
	}
	return { min, max };
}

socket.on("micro-signal", (msg) => {

	const bufferLeft = new Float32Array(msg.left);
	const bufferRight = new Float32Array(msg.right);

	const meanLeft = average(bufferLeft);
	const bufferLeftDC = bufferLeft.map((x) => x - meanLeft);
	const meanRight = average(bufferRight);
	const bufferRightDC = bufferRight.map((x) => x - meanRight);


	if (bufferLeftDC && bufferLeftDC.length > 0) {
		const { min, max } = fastMinMax(bufferLeftDC);
		singalLeftHistory.push({ min, max });
		if (singalLeftHistory.length > waveformCanvasLeft.width) {
			singalLeftHistory.shift();
		}
		drawWaveform(bufferLeftDC, waveformCanvasLeft, waveformCtxLeft);
	}
	if (bufferRightDC && bufferRightDC.length > 0) {
		const { min, max } = fastMinMax(bufferRightDC);
		signalRightHistory.push({ min, max });
		if (signalRightHistory.length > waveformCanvasRight.width) {
			signalRightHistory.shift();
		}
		drawWaveform(bufferRightDC, waveformCanvasRight, waveformCtxRight);
	}

	if (bufferLeftDC && bufferLeftDC.length > 0) {
		processAndDrawSpectrogram(bufferLeftDC);
	}

})

function mockMicroSignal() {

	const stereo = generateMockStereoSamples();

	const bufferLeft = stereo.filter((_, i) => i % 2 === 0);
	const bufferRight = stereo.filter((_, i) => i % 2 === 1);


	if (bufferLeft && bufferLeft.length > 0) {
		const min = Math.min(...bufferLeft);
		const max = Math.max(...bufferLeft);
		singalLeftHistory.push({ min, max });
		if (singalLeftHistory.length > waveformCanvasLeft.width) {
			singalLeftHistory.shift();
		}
		drawWaveform(bufferLeft, waveformCanvasLeft, waveformCtxLeft);
	}
	if (bufferRight && bufferRight.length > 0) {
		const min = Math.min(...bufferRight);
		const max = Math.max(...bufferRight);
		signalRightHistory.push({ min, max });
		if (signalRightHistory.length > waveformCanvasRight.width) {
			signalRightHistory.shift();
		}
		drawWaveform(bufferRight, waveformCanvasRight, waveformCtxRight);
	}

	if (bufferLeft && bufferLeft.length > 0) {
		processAndDrawSpectrogram(bufferLeft);
	}
}

function generateMockStereoSamples() {
	const monoSamples = Math.floor(sampleRate * interval / 1000);
	const totalSamples = monoSamples * 2;
	const stereo = new Int32Array(totalSamples);

	const freqLeft = Math.random() * 300 + 400;
	const ampLeft = Math.random() * 0.5 + 0.2;
	const phaseLeft = Math.random() * 2 * Math.PI;

	const freqRight = Math.random() * 300 + 900;
	const ampRight = Math.random() * 0.5 + 0.2;
	const phaseRight = Math.random() * 2 * Math.PI;

	for (let i = 0; i < monoSamples; i++) {
		const t = i / sampleRate;

		const valLeft = Math.sin(2 * Math.PI * freqLeft * t + phaseLeft);
		const valRight = Math.sin(2 * Math.PI * freqRight * t + phaseRight);

		const noiseL = (Math.random() - 0.5) * 0.05;
		const noiseR = (Math.random() - 0.5) * 0.05;

		const sampleLeft = Math.floor((valLeft * ampLeft + noiseL) * Math.pow(2, 26));
		const sampleRight = Math.floor((valRight * ampRight + noiseR) * Math.pow(2, 26));

		stereo[i * 2] = sampleLeft;
		stereo[i * 2 + 1] = sampleRight;
	}

	return stereo;
}

function drawWaveform(buffer, canvas, ctx) {
	const width = canvas.width;
	const height = canvas.height;
	const fullScale = 1 / waveformZoom;

	const imageData = ctx.getImageData(YAXIS_WAVEFORM_WIDTH + 1, 0, canvas.width - YAXIS_WAVEFORM_WIDTH - 1, canvas.height);
	ctx.putImageData(imageData, YAXIS_WAVEFORM_WIDTH, 0);

	drawWaveformLabels(canvas, ctx, fullScale);

	ctx.beginPath();

	const min = Math.min(...buffer);
	const max = Math.max(...buffer);

	const centerY = height / 2 + waveformOffset;

	const yMax = centerY - (max / fullScale) * height / 2;
	const yMin = centerY - (min / fullScale) * height / 2;

	ctx.moveTo(canvas.width - 5, yMin);
	ctx.lineTo(canvas.width - 5, yMax);

	ctx.strokeStyle = "blue";
	ctx.lineWidth = 1;
	ctx.stroke();

}

function drawWaveformLabels(canvas, ctx, fullScale) {

	const width = canvas.width;
	const height = canvas.height;
	const paddingY = 10;
	const availableHeight = height - 2 * paddingY;
	const centerY = height / 2 + waveformOffset;

	ctx.clearRect(0, 0, YAXIS_WAVEFORM_WIDTH, height);

	ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
	ctx.font = "10px sans-serif";
	ctx.textAlign = "right";
	ctx.textBaseline = "middle";
	ctx.strokeStyle = "rgba(0, 0, 0, 0.4)";
	ctx.lineWidth = 1;

	const numTicks = 7
	for (let i = 0; i < numTicks; i++) {
		const rel = i / (numTicks - 1);
		const y = paddingY + rel * availableHeight;

		const value = ((centerY - y) / (availableHeight / 2)) * fullScale * 2 ** 31;
		ctx.fillText(formatLargeNumber(value), YAXIS_WAVEFORM_WIDTH - 5, y);

		ctx.beginPath();
		ctx.moveTo(YAXIS_WAVEFORM_WIDTH, y);
		ctx.lineTo(width, y);
		ctx.stroke();
	}

}

function redrawWaveform(canvas, ctx, history) {
	console.log(history.length);
	const width = canvas.width;
	const height = canvas.height;
	const fullScale = 1 / waveformZoom;
	const centerY = height / 2 + waveformOffset;
	const colWidth = 1;
	const rightX = width - 5;

	ctx.clearRect(YAXIS_WAVEFORM_WIDTH, 0, width - YAXIS_WAVEFORM_WIDTH, height);

	const maxColumns = Math.floor((width - YAXIS_WAVEFORM_WIDTH - 5) / colWidth);
	const visibleHistory = history.slice(-maxColumns);

	ctx.strokeStyle = "blue";
	ctx.lineWidth = 1;

	for (let j = 0; j < visibleHistory.length; j++) {
		const { min, max } = visibleHistory[j];
		const x = rightX - (visibleHistory.length - 1 - j) * colWidth;
		const yMax = centerY - (max / fullScale) * (height / 2);
		const yMin = centerY - (min / fullScale) * (height / 2);

		ctx.beginPath();
		ctx.moveTo(x, yMin);
		ctx.lineTo(x, yMax);
		ctx.stroke();
	}

	drawWaveformLabels(canvas, ctx, fullScale);

}

function formatLargeNumber(val) {
	const absVal = Math.abs(val);
	if (absVal >= 1e9) return (val / 1e9).toFixed(2) + 'B';
	if (absVal >= 1e6) return (val / 1e6).toFixed(2) + 'M';
	if (absVal >= 1e3) return (val / 1e3).toFixed(2) + 'K';
	return val.toString();
}

function processAndDrawSpectrogram(samples) {
	for (let i = 0; i < samples.length; i++) specBuffer.push(samples[i]);

	while (specBuffer.length >= fftSize) {
		const chunk = specBuffer.slice(0, fftSize);
		specBuffer = specBuffer.slice(fftSize / 2);

		const input = new Float32Array(chunk);
		fft.forward(input);
		drawColumn(fft.spectrum);
	}
}

function drawColumn(spectrum) {
	storeSpectrumColumn(spectrum);

	const imageData = ctx.getImageData(
		YAXIS_SPECTROGRAM_WIDTH + 1,
		0,
		spectrogram.width - YAXIS_SPECTROGRAM_WIDTH - 1,
		spectrogram.height
	);
	ctx.putImageData(imageData, YAXIS_SPECTROGRAM_WIDTH, 0);

	renderColumnAtX(spectrum, spectrogram.width - 1);
	drawFrequencyLabels();
}

function drawFrequencyLabels() {
	const fontSize = 10;
	const numTicks = 10;
	const labelOffsetX = 2
	const spectrogramWidth = spectrogram.width;
	const spectrogramHeight = spectrogram.height;

	ctx.font = `${fontSize}px sans-serif`;
	ctx.textAlign = "left";
	ctx.textBaseline = "middle";
	ctx.fillStyle = "rgba(0, 0, 0, 0.7)";
	ctx.fillRect(0, 0, YAXIS_SPECTROGRAM_WIDTH, spectrogram.height);

	ctx.fillStyle = "white";

	ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
	ctx.lineWidth = 0.3;

	for (let i = 1; i <= numTicks - 2; i++) {
		const rel = i / (numTicks - 1);
		const y = rel * (spectrogramHeight - 1);
		const freq = yToFreq(y);

		ctx.fillText(`${freq} Hz`, labelOffsetX, y);

		ctx.beginPath();
		ctx.moveTo(YAXIS_SPECTROGRAM_WIDTH, y);
		ctx.lineTo(spectrogramWidth, y);
		ctx.stroke();
	}

}

function average(arr) {
	let sum = 0;
	for (let i = 0; i < arr.length; i++) {
		sum += arr[i];
	}
	return sum / arr.length;
}

function valueToHSL(value, freq) {
	const clamped = Math.max(0, Math.min(255, value));

	const hue = (freq / sampleRate) * sampleRate / 100;
	const saturation = 100;
	const lightness = (clamped / 255) * 50 + 10;

	return `hsl(${hue},${saturation}%,${lightness}%)`;
}

function clamp(val, min, max) {
	return Math.max(min, Math.min(max, val));
}

function yToIndex(y, SpectrumLen) {
	const H = spectrogram.height;
	const yVirtual = (y - specOffset) / specZoom;
	const rel = clamp(yVirtual / H, 0, 1);
	const relTopDown = 1 - rel;
	return Math.floor(relTopDown * (SpectrumLen - 1));
}

function yToFreq(y) {
	const nyquist = sampleRate / 2;
	const H = spectrogram.height;
	const yVirtual = (y - specOffset) / specZoom;
	const rel = clamp(yVirtual / H, 0, 1);
	const relTopDown = 1 - rel;
	return Math.floor(relTopDown * nyquist);
}

function freqToY(freq) {
	const nyquist = sampleRate / 2;
	const H = spectrogram.height;

	const rel = 1 - clamp(freq / nyquist, 0, 1);
	const yVirtual = rel * H;
	return yVirtual * specZoom + specOffset;
}

function storeSpectrumColumn(spectrum) {
	const col = Float32Array.from(spectrum);
	specHistory.push(col);

	const maxCols = spectrogram.width - YAXIS_SPECTROGRAM_WIDTH - 1;
	if (specHistory.length > maxCols) {
		specHistory.shift();
	}
}

function renderColumnAtX(spectrum, x) {
	const H = spectrogram.height;
	const dbMin = -120;
	const dbMax = 0;
	for (let y = 0; y < H; y++) {
		const idx = yToIndex(y, spectrum.length);
		const db = 20 * Math.log10(spectrum[idx] + 1e-6);

		let normDb = (db - dbMin) / (dbMax - dbMin);
		normDb = clamp(normDb, 0, 1);

		const rgbValue = Math.round(normDb * 255);
		const freq = idx * sampleRate / fftSize;

		const color = valueToHSL(rgbValue, freq);
		ctx.fillStyle = color;
		ctx.fillRect(x, y, 1, 1);

	}
}

function centerSpectrogramAt(freq) {
	const H = spectrogram.height;
	const yTarget = H / 2;
	const nyquist = sampleRate / 2;

	const f = clamp(freq, 0, nyquist);

	const rel = 1 - (f / nyquist);
	const yVirtual = rel * H;
	specOffset = yTarget - yVirtual * specZoom;
}

function redrawSpectrogram() {
	const W = spectrogram.width;
	const H = spectrogram.height;
	const rightX = W - 1;
	const drawAreaWidth = W - YAXIS_SPECTROGRAM_WIDTH - 1;

	ctx.clearRect(YAXIS_SPECTROGRAM_WIDTH, 0, drawAreaWidth, H);

	const visible = specHistory.slice(-drawAreaWidth);
	for (let j = 0; j < visible.length; j++) {
		const x = rightX - (visible.length - 1 - j);
		renderColumnAtX(visible[j], x);
	}
	drawFrequencyLabels();
}

function addSuffix(filename, suffix) {
	const dotIndex = filename.lastIndexOf('.');
	if (dotIndex === -1) {
		return filename + suffix;
	}
	return filename.slice(0, dotIndex) + suffix + filename.slice(dotIndex);
}

function onRecordStart({ filename, stream, setRecorder, setChunks }) {

	const chunks = [];

	const recorder = new MediaRecorder(stream, {
		mimeType: "video/webm; codecs=h264"
	})

	recorder.ondataavailable = (event) => {
		if (event.data.size > 0) {
			chunks.push(event.data);
		}
	}

	recorder.onstop = async () => {
		console.log('stopping');

		if (shouldUpload) {
			const blob = new Blob(chunks, { type: "video/webm" });
			const formData = new FormData();
			formData.append("file", blob, filename);

			await fetch("/upload", {
				method: "POST",
				body: formData
			});
		} else {
			console.warn("Backend forced not to upload video");
		}

	};

	setRecorder(recorder);
	setChunks(chunks);

}

function renderSelectOptions(selectElement, values, renderEmpty = true) {

	selectElement.innerHTML = "";

	if (renderEmpty) {
		const emptyOption = document.createElement("option");
		emptyOption.value = "";
		emptyOption.textContent = "";
		selectElement.appendChild(emptyOption);
	}

	values.forEach(val => {
		const option = document.createElement("option");
		option.value = val;
		option.textContent = val;
		selectElement.appendChild(option);
	})
}

async function loadConfig() {
	try {
		const res = await fetch("/config");
		if (!res.ok) throw new Error();
		return await res.json();
	} catch {
		console.warn("/api/config caused error. Default config to be used")
		return DEFAULT_CONFIG
	}
}

function gotDevices(deviceInfos) {
	// Handles being called several times to update labels. Preserve values.
	const values = selectors.map(select => select.value);
	selectors.forEach((select) => (select.innerHTML = ""));

	console.log(deviceInfos)

	deviceInfos.forEach((info) => {
		const option = document.createElement("option");
		option.value = info.deviceId
		option.text = info.label || `${info.kind}`

		if (info.kind == "audioinput") {
			audioInputSelect.appendChild(option)
		}
		if (info.kind == "videoinput") {
			const option1 = option.cloneNode(true);
			const option2 = option.cloneNode(true);
			videoSelect.appendChild(option1)
			videoSelect2.appendChild(option2)
		}
	});

	selectors.forEach((select, idx) => {
		if ([...select.childNodes].some((n) => n.value === values[idx])) {
			select.value = values[idx];
		}
	});
}

function setOutputDevices() {
	fetch('/get-audio-outputs')
		.then(res => res.json())
		.then(devices => {
			devices.forEach(device => {
				const option = document.createElement("option");
				option.value = device.name;
				option.textContent = device.name;
				microOutputSelect.appendChild(option);
			})
		})
}

function handleError(error) {
	console.log('navigator.MediaDevices.getUserMedia error: ', error.message, error.name);
}

function waitTrackLive(track) {
	if (track && track.readyState === 'live') {
		return Promise.resolve();
	}
	return new Promise(res => track.addEventListener('unmute', res, { once: true }));
}

function waitVideoPlaying(videoEl) {
	const ready = () => videoEl.readyState >= 2;
	const p = ready()
		? Promise.resolve()
		: new Promise(r => videoEl.addEventListener('loadeddata', r, { once: true }));

	return p.then(() => videoEl.play());
}

function startSimultaneously(...starts) {
	const mc = new MessageChannel();
	mc.port1.onmessage = () => starts.forEach(s => s());
	mc.port2.postMessage(null);
}

async function getSharedAudioTrack() {
	if (sharedAudioTrack && sharedAudioTrack.readyState === "live") {
		return sharedAudioTrack;
	}

	const audioSource = audioInputSelect.value;
	const audioStream = await navigator.mediaDevices.getUserMedia({
		audio: {
			deviceId: audioSource ? { exact: audioSource } : undefined
		},
		video: false
	});
	sharedAudioTrack = audioStream.getAudioTracks()[0];
	return sharedAudioTrack;

}

async function buildComposedStream(videoDeviceId) {
	const audioTrack = await getSharedAudioTrack();
	const videoStream = await navigator.mediaDevices.getUserMedia({
		video: {
			deviceId: videoDeviceId ? { exact: videoDeviceId } : undefined,
			width: { min: 640, ideal: 1280, max: 1280 },
			height: { min: 480, ideal: 720, max: 720 },
			frameRate: 30
		},
		audio: false
	});
	const videoTrack = videoStream.getVideoTracks()[0];

	const composed = new MediaStream([videoTrack, audioTrack]);
	return { composed, videoTrack }
}

// https://github.com/webrtc/samples/tree/gh-pages/src/content/devices/input-output
async function startFirstCamera() {

	try {
		const videoSource = videoSelect.value;
		const { composed } = await buildComposedStream(videoSource);
		localStream = composed;
		liveVideoElement.srcObject = localStream;
		await waitTrackLive(localStream.getAudioTracks()[0]);
		await waitVideoPlaying(liveVideoElement);
	} catch (e) {
		handleError(e);
	}

}

async function startSecondCamera() {
	try {
		const videoSource2 = videoSelect2.value;
		const { composed } = await buildComposedStream(videoSource2);
		localStream2 = composed;
		liveVideoElement2.srcObject = localStream2;
		await waitTrackLive(localStream2.getAudioTracks()[0]);
		await waitVideoPlaying(liveVideoElement2);
	} catch (e) {
		handleError(e);
	}
}

function selectMicroOutput() {
	const outputMicro = microOutputSelect.value;
	const payload = {
		micro_output: outputMicro
	}

	fetch('/set-micro-output', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	})
		.then(res => res.json())
		.then(data => {
			console.log("Microphone output set: ", data);
		})
		.catch(err => {
			console.error("Error setting microphone output: ", err);
		});
}


audioInputSelect.onchange = startFirstCamera;
videoSelect.onchange = startFirstCamera;
videoSelect2.onchange = startSecondCamera;
microOutputSelect.onchange = selectMicroOutput;


navigator.mediaDevices.ondevicechange = function (event) {
	log("mediaDevices.ondevicechange");
}

function log(message) {
	console.log(message)
}

function toggleButtons(automation_running) {
	startAutomationBt.disabled = automation_running;
	stopAutomationBt.disabled = !automation_running;
	startRecordingBt.disabled = automation_running;
	stopRecordingBt.disabled = !automation_running;
}

function startAutomation() {

	const material = materialsContainter.value;
	const speed = parseInt(speedSlider.value);
	const needleType = needleTypeContainer.value;
	const microphoneType = sensorVersionContainer.value;
	const description = descriptionEl.value;
	const iterInput = iterEl.value;
	const iterations = iterInput ? parseInt(iterInput, 10) || 1 : 1;
	const initX = parseInt(document.getElementById("initX").value);
	const finishX = parseInt(document.getElementById("finishX").value);
	const upZ = parseInt(document.getElementById("upZ").value);
	const downZ = parseInt(document.getElementById("downZ").value);
	const y = parseInt(document.getElementById("y").value);
	const r = parseInt(document.getElementById("r").value);
	const motionType = document.querySelector('input[name="motionType"]:checked').value;
	const sleepTime = parseInt(sleepTimeEl.value);

	let interval = upZ - downZ;
	if (intervalToggle.checked) {
		interval = parseInt(intervalEL.value);
	}

	if (iterations <= 0) {
		return alert("Iterations must be greater then 0");
	}
	if (motionType === "Up, Down, Forward" && finishX <= initX) {
		return alert("Finish X must be greater than Init X in 'Up, Down, Forward' motion type");
	}
	if (motionType === "Up, Down, Forward" && (finishX - initX) / iterations < 2) {
		alert("Your gap between punctures is very small: " + (finishX - initX) / iterations + " mm. But experiment is performing.");
	}

	const payload = {
		material: material,
		speed: speed,
		needleType: needleType,
		microphoneType: microphoneType,
		description: description,
		iterations: iterations,
		initX: initX,
		finishX: finishX,
		upZ: upZ,
		downZ: downZ,
		y: y,
		r: r,
		motionType: motionType,
		interval: interval,
		sleepTime: sleepTime
	};


	fetch("/run", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload)
	})
		.then(res => {
			if (!res.ok) throw new Error("Server error");
			return res.json();
		})
		.then(data => {
			startAutomationBt.disabled = true;
			console.log("Automation started: ", data);
		})
		.catch(err => {
			toggleButtons(false);
			console.error(err);
		})

}

function stopAutomation() {


	fetch("/stop", {
		method: "POST"
	})
		.then(res => {
			if (!res.ok) throw new Error("Server error");
			return res.json();
		})
		.then(data => {
			stopAutomationBt.disabled = true;
			console.log("Automation stopped: ", data);
			alert("Tests will be stopped after this iteration.");
		});

}

function updateRaspberryStatus(status) {
	raspberryStatusEl.textContent = `RaspberryPi status: ${status}`;
	raspberryStatusEl.style.color = status === "connected" ? "green" : "red";
}

async function getRaspberryStatus() {
	try {
		const res = await fetch("/raspberry-status");
		const data = await res.json();
		updateRaspberryStatus(data.status);
	} catch (err) {
		console.error("Error fetching RaspberryPi status: ", err);
		updateRaspberryStatus("Not connected");
	}

}

function startRecording() {

	const username = usernameEl.value.trim()
	const material = materialsContainter.value;
	const needleType = needleTypeContainer.value;
	const microphoneType = sensorVersionContainer.value;
	const description = descriptionEl.value;
	const duration = parseInt(recordingDurationEl?.value || "0");

	if (!username) {
		return alert("Please pass username");
	}

	const payload = {
		username: username,
		material: material,
		needleType: needleType,
		microphoneType: microphoneType,
		description: description,
	};

	fetch("/start-recording", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload)
	})
		.then(res => res.json())
		.then(data => {
			if (data.status == "ok") {
				toggleButtons(true);
				startRecordingTimer();
				stopAutomationBt.disabled = true;

				if (duration > 0) {
					setTimeout(() => {
						if (!stopRecordingBt.disabled) {
							stopRecording();
						}
					}, duration * 1000);
				}

			} else {
				console.warn("Failed to start recording: ", data.message);
			}
		})
		.catch(err => {
			console.error("Error starting recording: ", err);
		})
}

function stopRecording() {
	stopRecordingBt.disabled = true;
	fetch("/stop-recording", {
		method: "POST"
	})
		.then(res => res.json())
		.then(data => {
			if (data.status == "ok") {
				toggleButtons(false);
				stopRecordingTimer();
			}
		})
		.catch(err => {
			console.error("Error stopping recording: ", err);
		})
}

function updateFormVisibility() {
	if (toggle.checked) {
		automationForm.style.display = "none";
		manualForm.style.display = "block";
	} else {
		automationForm.style.display = "block";
		manualForm.style.display = "none";
	}
}

function startRecordingTimer() {
	recordingStartTime = Date.now();
	recordingTimerInterval = setInterval(() => {
		const duration = Math.floor((Date.now() - recordingStartTime) / 1000);
		timerEl.textContent = `Timer: ${duration}s`
	}, 1000);
}

function stopRecordingTimer() {
	clearInterval(recordingTimerInterval);
	timerEl.textContent = "Timer: 0s";
}

function deleteLastRecording() {
	deleteRecordingBt.disabled = true;
	fetch("/delete-last-recording", {
		method: "POST"
	})
		.then(res => res.json())
		.then(data => {

			if (data.status === "not found") {
				alert("No recordings found to delete");
			} else if (data.status === "ok") {
				alert("Deleted recordings: " + data.message);
			}

			deleteRecordingBt.disabled = false;
		})
		.catch(err => {
			console.error("Error deleting last recording: ", err);
		});
}

let isDataStreamRunning = false;
function toggleDataStream() {
	toggleDataStreamBt.disabled = true;
	if (!isDataStreamRunning) {
		fetch('/start-stream', { method: 'POST' })
			.then(res => res.json())
			.then(data => {
				if (data.status === 'ok') {
					isDataStreamRunning = true;
					toggleDataStreamBt.textContent = "Stop Live Data";
				} else {
					alert("Failed to start stream: " + (data.message || "Unknown error"));
				}
			})
			.catch(err => console.error(err))
			.finally(() => toggleDataStreamBt.disabled = false);
	} else {
		fetch('/stop-stream', { method: 'POST' })
			.then(res => res.json())
			.then(data => {
				if (data.status === 'ok') {
					isDataStreamRunning = false;
					toggleDataStreamBt.textContent = "Start Live Data";
				}
			})
			.catch(err => console.error(err))
			.finally(() => toggleDataStreamBt.disabled = false);
	}
}

async function detectCube() {
	try {
		if (!liveVideoElement || !liveVideoElement.srcObject) {
			alert("No live video stream available");
			return;
		}

		const video = liveVideoElement;
		const canvas = document.createElement("canvas");
		canvas.width = video.videoWidth;
		canvas.height = video.videoHeight;
		const canvasCtx = canvas.getContext("2d");

		canvasCtx.drawImage(video, 0, 0, canvas.width, canvas.height);

		const blob = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 1.0));
		const form = new FormData();
		form.append("frame", blob, "frame.jpg");

		const response = await fetch("/detect-cube", {
			method: "POST",
			body: form
		});
		if (!response.ok) {
			console.warn("Failed during detecting cube request", response.statusText);
		}
		const data = await response.json();

		if (!data.detected) {
			alert("Cube not detected");
			return;
		}

		cubeModalImage.src = data.image;
		cubeModal.style.display = "block";

	} catch (e) {
		console.error(e);
		alert("Error while detecting cube");
	}

}

async function applyFilterSettings() {

	const enabled = filterToggle.checked;
	const low = parseFloat(bpLowEl.value);
	const high = parseFloat(bpHighEl.value);

	applyFilterBt.disabled = true;

	try {
		const res = await fetch("/set-micro-filter", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				enabled: enabled,
				low: low,
				high: high
			})
		});
		if (!res.ok) throw new Error("Server error");
	} catch (e) {
		console.error("Error applying filter settings: ", e);
	} finally {
		applyFilterBt.disabled = false;
	}

}

(async function init() {

	const cfg = await loadConfig();
	renderSelectOptions(materialsContainter, cfg.materials, true);
	renderSelectOptions(needleTypeContainer, cfg.needleTypes, true);
	renderSelectOptions(sensorVersionContainer, cfg.sensorVersions, true);

	// for getting devices and permissions
	const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
	stream.getTracks().forEach((t) => t.stop())
	const devices = await navigator.mediaDevices.enumerateDevices();
	gotDevices(devices);
	setOutputDevices()
	startFirstCamera();
	startSecondCamera();

})();

toggleDataStreamBt.addEventListener("click", toggleDataStream);
startAutomationBt.addEventListener("click", startAutomation);
stopAutomationBt.addEventListener("click", stopAutomation);
startRecordingBt.addEventListener("click", startRecording);
stopRecordingBt.addEventListener("click", stopRecording);
deleteRecordingBt.addEventListener("click", deleteLastRecording);
toggle.addEventListener("change", updateFormVisibility);
speedSlider.addEventListener("input", (e) => {
	speedValueEl.textContent = e.target.value;
})
intervalToggle.addEventListener("change", (e) => {
	intervalEL.style.display = e.target.checked ? "block" : "none";
})
detectCubeBt.addEventListener("click", detectCube);
cubeModalClose.addEventListener("click", () => cubeModal.style.display = "none");
cubeModal.addEventListener("click", (e) => {
	if (e.target === cubeModal) {
		cubeModal.style.display = "none";
	}
})
filterToggle.addEventListener("change", () => {

	if (filterToggle.checked) {
		filterFields.classList.remove("hidden");
	} else {
		filterFields.classList.add("hidden");
		applyFilterSettings();
	}

})
applyFilterBt.addEventListener("click", applyFilterSettings);
setInterval(getRaspberryStatus, 3000);
// setInterval(mockMicroSignal, interval);

/// waveforms scaling
waveformCanvasLeft.addEventListener('mousedown', (e) => {
	if (e.ctrlKey) {
		isCtrlZoomingWaveform = true;
	} else {
		isPanningWaveform = true;
	}
	lastYWaveform = e.clientY;

});

waveformCanvasLeft.addEventListener('mousemove', (e) => {
	if (isCtrlZoomingWaveform) {
		const deltaY = e.clientY - lastYWaveform;
		lastYWaveform = e.clientY;

		waveformZoom *= (1 - deltaY * 0.01);
		waveformZoom = Math.max(1, Math.min(waveformZoom, 100));
		redrawWaveform(waveformCanvasLeft, waveformCtxLeft, singalLeftHistory);
		redrawWaveform(waveformCanvasRight, waveformCtxRight, signalRightHistory);
	} else if (isPanningWaveform) {
		const deltaY = e.clientY - lastYWaveform;
		lastYWaveform = e.clientY;

		waveformOffset += deltaY;
		redrawWaveform(waveformCanvasLeft, waveformCtxLeft, singalLeftHistory);
		redrawWaveform(waveformCanvasRight, waveformCtxRight, signalRightHistory);
	}
});

waveformCanvasLeft.addEventListener('mouseup', () => {
	isCtrlZoomingWaveform = false;
	isPanningWaveform = false;
	lastYWaveform = null;
});

/// spectrogram scaling
applySpecScaleBt.addEventListener('click', () => {
	console.log("Apply spectrogram scale");
	const centerFreq = parseFloat(specCenterFreqEl.value);
	const zoom = parseFloat(specZoomEl.value);

	specZoom = clamp(zoom, 1, 1000);
	centerSpectrogramAt(centerFreq);
	redrawSpectrogram();
});

///Shortcuts

document.addEventListener('keydown', (e) => {
	if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
		return;
	}

	if (e.code === "Space") {
		e.preventDefault();

		if (toggle.checked) {
			if (!startRecordingBt.disabled) {
				startRecording();
			} else if (!stopRecordingBt.disabled) {
				stopRecording();
			}
		}

	}

})

// Meter class that generates a number correlated to audio volume.
// The meter class itself displays nothing, but it makes the
// instantaneous and time-decaying volumes available for inspection.
// It also reports on the fraction of samples that were at or near
// the top of the measurement range.
function SoundMeter(context) {
	this.context = context;
	this.instant = 0.0;
	this.slow = 0.0;
	this.clip = 0.0;
	this.script = context.createScriptProcessor(2048, 1, 1);
	var that = this;
	this.script.onaudioprocess = function (event) {
		var input = event.inputBuffer.getChannelData(0);
		var i;
		var sum = 0.0;
		var clipcount = 0;
		for (i = 0; i < input.length; ++i) {
			sum += input[i] * input[i];
			if (Math.abs(input[i]) > 0.99) {
				clipcount += 1;
			}
		}
		that.instant = Math.sqrt(sum / input.length);
		that.slow = 0.95 * that.slow + 0.05 * that.instant;
		that.clip = clipcount / input.length;
	};
}

SoundMeter.prototype.connectToSource = function (stream, callback) {
	console.log('SoundMeter connecting');
	try {
		this.mic = this.context.createMediaStreamSource(stream);
		this.mic.connect(this.script);
		// necessary to make sample run, but should not be.
		this.script.connect(this.context.destination);
		if (typeof callback !== 'undefined') {
			callback(null);
		}
	} catch (e) {
		console.error(e);
		if (typeof callback !== 'undefined') {
			callback(e);
		}
	}
};
SoundMeter.prototype.stop = function () {
	this.mic.disconnect();
	this.script.disconnect();
};


//browser ID
function getBrowser() {
	var nVer = navigator.appVersion;
	var nAgt = navigator.userAgent;
	var browserName = navigator.appName;
	var fullVersion = '' + parseFloat(navigator.appVersion);
	var majorVersion = parseInt(navigator.appVersion, 10);
	var nameOffset, verOffset, ix;

	// In Opera, the true version is after "Opera" or after "Version"
	if ((verOffset = nAgt.indexOf("Opera")) != -1) {
		browserName = "Opera";
		fullVersion = nAgt.substring(verOffset + 6);
		if ((verOffset = nAgt.indexOf("Version")) != -1)
			fullVersion = nAgt.substring(verOffset + 8);
	}
	// In MSIE, the true version is after "MSIE" in userAgent
	else if ((verOffset = nAgt.indexOf("MSIE")) != -1) {
		browserName = "Microsoft Internet Explorer";
		fullVersion = nAgt.substring(verOffset + 5);
	}
	// In Chrome, the true version is after "Chrome"
	else if ((verOffset = nAgt.indexOf("Chrome")) != -1) {
		browserName = "Chrome";
		fullVersion = nAgt.substring(verOffset + 7);
	}
	// In Safari, the true version is after "Safari" or after "Version"
	else if ((verOffset = nAgt.indexOf("Safari")) != -1) {
		browserName = "Safari";
		fullVersion = nAgt.substring(verOffset + 7);
		if ((verOffset = nAgt.indexOf("Version")) != -1)
			fullVersion = nAgt.substring(verOffset + 8);
	}
	// In Firefox, the true version is after "Firefox"
	else if ((verOffset = nAgt.indexOf("Firefox")) != -1) {
		browserName = "Firefox";
		fullVersion = nAgt.substring(verOffset + 8);
	}
	// In most other browsers, "name/version" is at the end of userAgent
	else if ((nameOffset = nAgt.lastIndexOf(' ') + 1) <
		(verOffset = nAgt.lastIndexOf('/'))) {
		browserName = nAgt.substring(nameOffset, verOffset);
		fullVersion = nAgt.substring(verOffset + 1);
		if (browserName.toLowerCase() == browserName.toUpperCase()) {
			browserName = navigator.appName;
		}
	}
	// trim the fullVersion string at semicolon/space if present
	if ((ix = fullVersion.indexOf(";")) != -1)
		fullVersion = fullVersion.substring(0, ix);
	if ((ix = fullVersion.indexOf(" ")) != -1)
		fullVersion = fullVersion.substring(0, ix);

	majorVersion = parseInt('' + fullVersion, 10);
	if (isNaN(majorVersion)) {
		fullVersion = '' + parseFloat(navigator.appVersion);
		majorVersion = parseInt(navigator.appVersion, 10);
	}


	return browserName;
}
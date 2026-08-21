'use strict';

/* globals MediaRecorder */
// Spec is at http://dvcs.w3.org/hg/dap/raw-file/tip/media-stream-capture/RecordingProposal.html


const iterEl = document.getElementById("iterations");
const repetitionsEl = document.getElementById("repetitions")
const descriptionEl = document.getElementById("description");
const startAutomationBt = document.getElementById("startTests");
const stopAutomationBt = document.getElementById("stopTests");
const automationStatusEl = document.getElementById("automationStatus");
const iterationCounterEl = document.getElementById("iterationCounter");
const deleteRecordingBt = document.getElementById("deleteRecording");

const usernameEl = document.getElementById("username");
const modeToggle = document.getElementById("modeToggle");
const startRecordingBt = document.getElementById("startRecording");
const stopRecordingBt = document.getElementById("stopRecording");
const manualForm = document.getElementById("manualForm");


const speedSlider = document.getElementById("speed");
const speedValueEl = document.getElementById("speedValue");
const timerEl = document.getElementById("recordingTimer");

const audioInputSelect = document.getElementById("audioSource");
const videoSelect = document.getElementById("videoSource");
const videoSelect2 = document.getElementById("videoSource2");
const selectors = [audioInputSelect, videoSelect, videoSelect2];

const liveVideoElement = document.getElementById('video');
const liveVideoElement2 = document.getElementById('video2');
const resVideo1El = document.getElementById("resVideo1");
const resVideo2El = document.getElementById("resVideo2");

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
let camStartTimestamp = null;

const automationForm = document.getElementById("automationForm");
const initialSleepTimeEl = document.getElementById("initialSleepTime");
const sleepTimeEl = document.getElementById("sleepTime");
const pointsContainer = document.getElementById("pointsContainer");
const addPointBtn = document.getElementById("addPointBtn");
const pathModeEl = document.getElementById("pathMode");
const pointsPathForm = document.getElementById("pointsPathForm");
const arcPathForm = document.getElementById("arcPathForm");
const arcCenterXEl = document.getElementById("arcCenterX");
const arcCenterYEl = document.getElementById("arcCenterY");
const arcZEl = document.getElementById("arcZ");
const arcRadiusEl = document.getElementById("arcRadius");
const arcPointsPreviewEl = document.getElementById("arcPointsPreview");
const toggleUsgBtn = document.getElementById("toggleUsgBtn");

let isUsgOn = false;

const deviceUSG = document.getElementById("deviceUSG");
const trackerIMU = document.getElementById("trackerIMU");
const trackerPSMove = document.getElementById("trackerPSMove");
const deviceMEMS = document.getElementById("deviceMEMS");
const deviceUSGStatus = document.getElementById("deviceUSGStatus");
const trackerIMUStatus = document.getElementById("trackerIMUStatus");
const trackerPSMoveStatus = document.getElementById("trackerPSMoveStatus");
const deviceMEMSStatus = document.getElementById("deviceMEMSStatus");
const usgStream = document.getElementById("usgStream");

const socket = io();
socket.on("connect", () => {
	console.log("Socket.io connected from browser")
})

socket.on("record", async (msg) => {

	const action = msg.action;
	const filename = msg.filename;
	console.log(action);

	if (!localStream && !localStream2) {
		console.warn("No media stream available to record");
		return;
	}

	if (action === "start") {

		const starts = [];

		if (localStream) {
			onRecordStart({
				filename: addSuffix(filename, "_cam1"),
				stream: localStream,
				setRecorder: (recorder) => mediaRecorder = recorder,
				setChunks: (chunks) => recordedChunks = chunks,
			});
			starts.push(() => mediaRecorder.start());
		}

		if (localStream2) {
			onRecordStart({
				filename: addSuffix(filename, "_cam2"),
				stream: localStream2,
				setRecorder: (recorder) => mediaRecorder2 = recorder,
				setChunks: (chunks) => recordedChunks2 = chunks,
			});
			starts.push(() => mediaRecorder2.start());
		}

		console.log("Browser started recording");
		if (starts.length > 0) {
			startSimultaneously(...starts);
		}

	}

	console.log(mediaRecorder, mediaRecorder2);
	if (action === "stop") {
		const isRecording1 = mediaRecorder && mediaRecorder.state === "recording";
		const isRecording2 = mediaRecorder2 && mediaRecorder2.state === "recording";

		if (isRecording1 || isRecording2) {
			shouldUpload = msg.shouldUpload;
			if (!shouldUpload) {
				alert("Recording is not saved!")
			}

			if (isRecording1) mediaRecorder.requestData();
			if (isRecording2) mediaRecorder2.requestData();

			Promise.resolve().then(() => {
				if (isRecording1) mediaRecorder.stop();
				if (isRecording2) mediaRecorder2.stop();
				console.log("Browser stopped recording");
			});
		}
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
		mimeType: "video/webm; codecs=vp9",
		videoBitsPerSecond: 100000000
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
			if (camStartTimestamp !== null) {
				formData.append("start_timestamp", camStartTimestamp);
			}

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

function getDevices(deviceInfos) {
	// Handles being called several times to update labels. Preserve values.
	const values = selectors.map(select => select.value);
	selectors.forEach((select) => {
		select.innerHTML = "";
		const noneOption = document.createElement("option");
		noneOption.value = "none";
		noneOption.text = "None";
		select.appendChild(noneOption);
	});

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

function handleError(error) {
	console.log('navigator.MediaDevices.getUserMedia error: ', error.message, error.name);
}

function waitTrackLive(track) {
	if (!track) return Promise.resolve();
	if (track.readyState === 'live') {
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
	mc.port1.onmessage = () => {
		camStartTimestamp = Date.now() / 1000;
		starts.forEach(s => s());
	};
	mc.port2.postMessage(null);
}

async function getSharedAudioTrack() {
	if (sharedAudioTrack && sharedAudioTrack.readyState === "live") {
		return sharedAudioTrack;
	}

	const audioSource = audioInputSelect.value;
	if (audioSource === "none") {
		return null;
	}
	const audioStream = await navigator.mediaDevices.getUserMedia({
		audio: {
			deviceId: audioSource ? { exact: audioSource } : undefined
		},
		video: false
	});
	sharedAudioTrack = audioStream.getAudioTracks()[0];
	return sharedAudioTrack;

}

async function buildComposedStream(videoDeviceId, targetWidth, targetHeight) {
	const audioTrack = await getSharedAudioTrack();
	const videoStream = await navigator.mediaDevices.getUserMedia({
		video: {
			deviceId: videoDeviceId ? { exact: videoDeviceId } : undefined,
			width: { exact: targetWidth },
			height: { exact: targetHeight },
			frameRate: 30
		},
		audio: false
	});
	const videoTrack = videoStream.getVideoTracks()[0];

	const tracks = [videoTrack];
	if (audioTrack) {
		tracks.push(audioTrack);
	}
	const composed = new MediaStream(tracks);
	return { composed, videoTrack }
}

// https://github.com/webrtc/samples/tree/gh-pages/src/content/devices/input-output
async function startFirstCamera() {

	try {
		const videoSource = videoSelect.value;
		if (videoSource === "none") {
			if (localStream) {
				localStream.getVideoTracks().forEach(t => t.stop());
				localStream = null;
				liveVideoElement.srcObject = null;
				resVideo1El.textContent = "";
			}
			return;
		}
		if (localStream) {
			localStream.getVideoTracks().forEach(t => t.stop());
			localStream = null;
			liveVideoElement.srcObject = null;
		}
		const { composed, videoTrack } = await buildComposedStream(videoSource, 640, 360);
		localStream = composed;
		liveVideoElement.srcObject = localStream;
		await waitTrackLive(localStream.getAudioTracks()[0]);
		await waitVideoPlaying(liveVideoElement);

		const settings = videoTrack.getSettings();
		resVideo1El.textContent = `Cam 1: ${settings.width}x${settings.height}`;
	} catch (e) {
		handleError(e);
	}

}

async function startSecondCamera() {
	try {
		const videoSource2 = videoSelect2.value;
		if (videoSource2 === "none") {
			if (localStream2) {
				localStream2.getVideoTracks().forEach(t => t.stop());
				localStream2 = null;
				liveVideoElement2.srcObject = null;
				resVideo2El.textContent = "";
			}
			return;
		}
		if (localStream2) {
			localStream2.getVideoTracks().forEach(t => t.stop());
			localStream2 = null;
			liveVideoElement2.srcObject = null;
		}
		if (videoSource2 === videoSelect.value) {
			console.warn("Second camera uses the same device as the first. Skipping to avoid timeout.");
			resVideo2El.textContent = "";
			return;
		}
		const { composed, videoTrack } = await buildComposedStream(videoSource2, 1920, 1080);
		localStream2 = composed;
		liveVideoElement2.srcObject = localStream2;
		await waitTrackLive(localStream2.getAudioTracks()[0]);
		await waitVideoPlaying(liveVideoElement2);

		const settings = videoTrack.getSettings();
		resVideo2El.textContent = `Cam 2: ${settings.width}x${settings.height}`;
	} catch (e) {
		handleError(e);
	}
}

async function restartCamerasForAudioChange() {
	if (sharedAudioTrack) {
		sharedAudioTrack.stop();
		sharedAudioTrack = null;
	}
	await startFirstCamera();
	await startSecondCamera();
}

audioInputSelect.onchange = restartCamerasForAudioChange;
videoSelect.onchange = startFirstCamera;
videoSelect2.onchange = startSecondCamera;


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
	toggleUsgBtn.disabled = automation_running;
	deviceMEMS.disabled = automation_running;
	audioInputSelect.disabled = automation_running;
}

function readCommonAutomationParams() {
	const speed = parseInt(speedSlider.value);
	const description = descriptionEl.value;
	const iterInput = iterEl.value;
	const iterations = iterInput ? parseInt(iterInput, 10) || 1 : 1;
	const repetitionsInput = repetitionsEl.value;
	const repetitions = repetitionsInput ? parseInt(repetitionsInput, 10) || 1 : 1;
	const initialSleepTime = parseInt(initialSleepTimeEl.value);
	const sleepTime = parseInt(sleepTimeEl.value);

	if (iterations <= 0) {
		throw new Error("Iterations must be greater than 0.");
	}
	if (repetitions <= 0) {
		throw new Error("Repetitions must be greater than 0.");
	}

	return {
		speed,
		description,
		iterations,
		repetitions,
		initialSleepTime,
		sleepTime
	};
}

function startSelectedAutomation() {
	let commonParams;
	try {
		commonParams = readCommonAutomationParams();
	} catch (error) {
		return alert(error.message);
	}

	const startForMode = automationModeStarters[pathModeEl.value];
	if (!startForMode) {
		return alert("Unsupported Dobot movement type.");
	}
	return startForMode(commonParams);
}

function startPointAutomation(commonParams) {
	const points = Array.from(document.querySelectorAll('.point-row')).map(row => {
		return {
			x: parseFloat(row.querySelector('.point-x').value) || 0,
			y: parseFloat(row.querySelector('.point-y').value) || 0,
			z: parseFloat(row.querySelector('.point-z').value) || 0,
			r: parseFloat(row.querySelector('.point-r').value) || 0
		};
	});

	if (points.length === 0) {
		return alert("Please add at least one point.");
	}

	const payload = {
		...commonParams,
		points: points,
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

function readFiniteNumber(element, label) {
	const value = Number(element.value);
	if (!Number.isFinite(value)) {
		throw new Error(`${label} must be a valid number.`);
	}
	return value;
}

function arcPoints(centerX, centerY, z, radius) {
	return {
		start: { x: centerX, y: centerY - radius, z: z, r: 90 },
		mid: { x: centerX - radius, y: centerY, z: z, r: 0 },
		end: { x: centerX, y: centerY + radius, z: z, r: -90 }
	};
}

function updateArcPreview() {
	try {
		const centerX = readFiniteNumber(arcCenterXEl, "Center X");
		const centerY = readFiniteNumber(arcCenterYEl, "Center Y");
		const z = readFiniteNumber(arcZEl, "Fixed Z");
		const radius = readFiniteNumber(arcRadiusEl, "Radius");
		const points = arcPoints(centerX, centerY, z, radius);
		const format = point => `X=${point.x.toFixed(2)}, Y=${point.y.toFixed(2)}, Z=${point.z.toFixed(2)}, R=${point.r.toFixed(2)}`;
		arcPointsPreviewEl.textContent = `Start: ${format(points.start)}\nMid:   ${format(points.mid)}\nEnd:   ${format(points.end)}`;
	} catch (error) {
		arcPointsPreviewEl.textContent = error.message;
	}
}

function startArcAutomation(commonParams) {
	let centerX;
	let centerY;
	let z;
	let radius;
	try {
		centerX = readFiniteNumber(arcCenterXEl, "Center X");
		centerY = readFiniteNumber(arcCenterYEl, "Center Y");
		z = readFiniteNumber(arcZEl, "Fixed Z");
		radius = readFiniteNumber(arcRadiusEl, "Radius");
	} catch (error) {
		return alert(error.message);
	}

	if (radius <= 0) {
		return alert("Radius must be greater than 0.");
	}

	const payload = {
		...commonParams,
		centerX,
		centerY,
		z,
		radius
	};

	fetch("/run-arc", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload)
	})
		.then(async response => {
			const data = await response.json();
			if (!response.ok) throw new Error(data.error || "Server error");
			return data;
		})
		.then(data => {
			startAutomationBt.disabled = true;
			console.log("Arc automation started: ", data);
		})
		.catch(error => {
			toggleButtons(false);
			console.error(error);
			alert("Failed to start arc automation: " + error.message);
		});
}

const automationModeStarters = {
	points: startPointAutomation,
	arc180: startArcAutomation
};

function updatePathMode() {
	const isArc = pathModeEl.value === "arc180";
	pointsPathForm.style.display = isArc ? "none" : "flex";
	arcPathForm.style.display = isArc ? "flex" : "none";
	if (isArc) updateArcPreview();
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

function addPointRow() {
	const row = document.createElement("div");
	row.className = "point-row param-pair";
	row.innerHTML = `
		<div class="param-group-wrapper"><input type="number" class="point-x" placeholder="X" /></div>
		<div class="param-group-wrapper"><input type="number" class="point-y" placeholder="Y" /></div>
		<div class="param-group-wrapper"><input type="number" class="point-z" placeholder="Z" /></div>
		<div class="param-group-wrapper"><input type="number" class="point-r" placeholder="R" /></div>
		<button type="button" class="remove-point-btn small-btn">X</button>
	`;
	if (pointsContainer) pointsContainer.appendChild(row);
	row.querySelector('.remove-point-btn').addEventListener('click', () => row.remove());
}

function startManualRecording() {
	const description = descriptionEl.value;
	const username = usernameEl.value.trim();

	if (!username) {
		return alert("Please pass username");
	}
	fetch("/start-manual", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ description: description, username: username })
	})
		.then(async res => {
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || data.message || "Server error");
			return data;
		})
		.then(data => {
			if (data.status === "ok") {
				toggleButtons(true);
				startRecordingTimer();
				stopAutomationBt.disabled = true;
			} else {
				console.warn("Failed to start recording: ", data.message);
			}
		})
		.catch(err => {
			console.error("Error starting recording: ", err);
			alert("Failed to start recording: " + err.message);
		});
}

function stopManualRecording() {
	stopRecordingBt.disabled = true;
	fetch("/stop-manual", { method: "POST" })
		.then(res => res.json())
		.then(data => {
			if (data.status === "ok") {
				toggleButtons(false);
				stopRecordingTimer();
			}
		})
		.catch(err => {
			console.error("Error stopping recording: ", err);
		});
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

function updateDeviceStatus(element, status) {
	element.className = `device-status ${status}`;
}

function handleUsgToggle(checkbox, statusElement) {
	const enable = checkbox.checked;
	checkbox.disabled = true;
	updateDeviceStatus(statusElement, 'loading');

	fetch("/device-usg-toggle", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ enable: enable })
	})
		.then(res => res.json())
		.then(data => {
			if (data.status === "ok") {
				updateDeviceStatus(statusElement, data.state);
			} else {
				alert("Error toggling USG: " + data.message);
				checkbox.checked = !enable; // revert
				updateDeviceStatus(statusElement, 'error');
			}
		})
		.catch(err => {
			console.error("Error toggling USG:", err);
			checkbox.checked = !enable; // revert
			updateDeviceStatus(statusElement, 'error');
		})
		.finally(() => {
			checkbox.disabled = false;
		});
}

function handleTrackerToggle(trackerName, checkbox, statusElement) {
	const enable = checkbox.checked;
	checkbox.disabled = true;
	updateDeviceStatus(statusElement, 'loading');

	fetch("/device-tracker-toggle", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ tracker: trackerName, enable: enable })
	})
		.then(res => res.json())
		.then(data => {
			if (data.status === "ok") {
				updateDeviceStatus(statusElement, data.state);
			} else {
				alert("Error toggling Tracker: " + data.message);
				checkbox.checked = !enable; // revert
				updateDeviceStatus(statusElement, 'error');
			}
		})
		.catch(err => {
			console.error("Error toggling Tracker:", err);
			checkbox.checked = !enable; // revert
			updateDeviceStatus(statusElement, 'error');
		})
		.finally(() => {
			checkbox.disabled = false;
		});
}

function handleMemsToggle() {
	const enable = deviceMEMS.checked;
	deviceMEMS.disabled = true;
	updateDeviceStatus(deviceMEMSStatus, "loading");

	fetch("/device-mems-toggle", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ enable: enable })
	})
		.then(async response => {
			const data = await response.json();
			if (!response.ok || data.status !== "ok") {
				throw new Error(data.message || "Could not toggle MEMS microphone");
			}
			updateDeviceStatus(deviceMEMSStatus, data.state);
		})
		.catch(error => {
			console.error("Error toggling Raspberry Pi MEMS microphone:", error);
			deviceMEMS.checked = !enable;
			updateDeviceStatus(deviceMEMSStatus, "error");
			alert("Error toggling Raspberry Pi MEMS microphone: " + error.message);
		})
		.finally(() => {
			deviceMEMS.disabled = false;
		});
}

(async function init() {

	// for getting devices and permissions
	const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
	stream.getTracks().forEach((t) => t.stop())
	const devices = await navigator.mediaDevices.enumerateDevices();
	getDevices(devices);

	await startFirstCamera();
	await startSecondCamera();

	// Fetch device status and update UI
	fetch("/device-status")
		.then(res => res.json())
		.then(data => {
			if (data.usg) {
				deviceUSG.checked = data.usg.enabled;
				updateDeviceStatus(deviceUSGStatus, data.usg.enabled ? (data.usg.initialized ? 'on' : 'error') : 'off');
			}
			if (data.tracker_imu) {
				trackerIMU.checked = data.tracker_imu.enabled;
				updateDeviceStatus(trackerIMUStatus, data.tracker_imu.enabled ? (data.tracker_imu.initialized ? 'on' : 'error') : 'off');
			}
			if (data.tracker_psmove) {
				trackerPSMove.checked = data.tracker_psmove.enabled;
				updateDeviceStatus(trackerPSMoveStatus, data.tracker_psmove.enabled ? (data.tracker_psmove.initialized ? 'on' : 'error') : 'off');
			}
			if (data.mems) {
				deviceMEMS.checked = data.mems.enabled;
				updateDeviceStatus(deviceMEMSStatus, data.mems.enabled ? (data.mems.initialized ? 'on' : 'error') : 'off');
			}
		})
		.catch(err => console.error("Error fetching device status:", err));

})();


modeToggle.addEventListener("change", function () {
	if (modeToggle.checked) {
		automationForm.style.display = "none";
		manualForm.style.display = "block";
	} else {
		automationForm.style.display = "block";
		manualForm.style.display = "none";
	}
});

startAutomationBt.addEventListener("click", startSelectedAutomation);
stopAutomationBt.addEventListener("click", stopAutomation);
startRecordingBt.addEventListener("click", startManualRecording);
stopRecordingBt.addEventListener("click", stopManualRecording);
deleteRecordingBt.addEventListener("click", deleteLastRecording);
speedSlider.addEventListener("input", (e) => {
	speedValueEl.textContent = e.target.value;
})
addPointBtn.addEventListener("click", addPointRow);
pathModeEl.addEventListener("change", updatePathMode);
[arcCenterXEl, arcCenterYEl, arcZEl, arcRadiusEl].forEach(element => {
	element.addEventListener("input", updateArcPreview);
});
deviceUSG.addEventListener("change", () => handleUsgToggle(deviceUSG, deviceUSGStatus));
trackerIMU.addEventListener("change", () => handleTrackerToggle("imu", trackerIMU, trackerIMUStatus));
trackerPSMove.addEventListener("change", () => handleTrackerToggle("psmove", trackerPSMove, trackerPSMoveStatus));
deviceMEMS.addEventListener("change", handleMemsToggle);


toggleUsgBtn.addEventListener("click", () => {
	if (!deviceUSG.checked) {
		alert("USG Scanner is not enabled. Please enable it first.");
		return;
	}
	isUsgOn = !isUsgOn;
	const action = isUsgOn ? "turn_on" : "turn_off";
	toggleUsgBtn.disabled = true;
	fetch("/usg-toggle", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ action: action })
	}).then(res => res.json()).then(data => {
		if (data.status === "ok") {
			toggleUsgBtn.textContent = isUsgOn ? "Stop USG preview" : "Start USG preview";
			if (usgStream) {
				if (isUsgOn) {
					// Append timestamp to avoid caching
					usgStream.src = "/usg_feed?" + new Date().getTime();
					usgStream.style.display = "block";
				} else {
					usgStream.src = "";
					usgStream.style.display = "none";
				}
			}
		} else {
			isUsgOn = !isUsgOn;
			alert(data.message);
		}
	}).finally(() => {
		toggleUsgBtn.disabled = false;
	});
});

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

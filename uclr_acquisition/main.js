'use strict';

/* globals MediaRecorder */
// Spec is at http://dvcs.w3.org/hg/dap/raw-file/tip/media-stream-capture/RecordingProposal.html


const iterEl = document.getElementById("iterations");
const descriptionEl = document.getElementById("description");
const startAutomationBt = document.getElementById("startTests");
const stopAutomationBt = document.getElementById("stopTests");
const automationStatusEl = document.getElementById("automationStatus");
const iterationCounterEl = document.getElementById("iterationCounter");
const deleteRecordingBt = document.getElementById("deleteRecording");


const speedSlider = document.getElementById("speed");
const speedValueEl = document.getElementById("speedValue");
const timerEl = document.getElementById("recordingTimer");

const audioInputSelect = document.getElementById("audioSource");
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

const automationForm = document.getElementById("automationForm");
const sleepTimeEl = document.getElementById("sleepTime");
const pointsContainer = document.getElementById("pointsContainer");
const addPointBtn = document.getElementById("addPointBtn");
const toggleUsgBtn = document.getElementById("toggleUsgBtn");

let isUsgOn = false;

const DEFAULT_CONFIG = {
	speeds: ["slow", "medium", "fast"]
};

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




audioInputSelect.onchange = startFirstCamera;
videoSelect.onchange = startFirstCamera;
videoSelect2.onchange = startSecondCamera;


navigator.mediaDevices.ondevicechange = function (event) {
	log("mediaDevices.ondevicechange");
}

function log(message) {
	console.log(message)
}

function toggleButtons(automation_running) {
	if (automation_running === true) {
		startAutomationBt.disabled = true;
		stopAutomationBt.disabled = false;
		if (toggleUsgBtn) toggleUsgBtn.disabled = true;
		automationForm.classList.add("disabled");
		document.querySelectorAll("#automationForm input, #automationForm select, #automationForm button").forEach(el => el.disabled = true);
	} else {
		startAutomationBt.disabled = false;
		stopAutomationBt.disabled = true;
		if (toggleUsgBtn) toggleUsgBtn.disabled = false;
		automationForm.classList.remove("disabled");
		document.querySelectorAll("#automationForm input, #automationForm select, #automationForm button").forEach(el => el.disabled = false);
	}
}

function startAutomation() {

	const speed = parseInt(speedSlider.value);
	const description = descriptionEl.value;
	const iterInput = iterEl.value;
	const iterations = iterInput ? parseInt(iterInput, 10) || 1 : 1;
	const sleepTime = parseInt(sleepTimeEl.value);

	if (iterations <= 0) {
		return alert("Iterations must be greater then 0");
	}

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
		speed: speed,
		description: description,
		iterations: iterations,
		points: points,
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

(async function init() {

	const cfg = await loadConfig();


	// for getting devices and permissions
	const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
	stream.getTracks().forEach((t) => t.stop())
	const devices = await navigator.mediaDevices.enumerateDevices();
	gotDevices(devices);

	startFirstCamera();
	startSecondCamera();

})();

startAutomationBt.addEventListener("click", startAutomation);
stopAutomationBt.addEventListener("click", stopAutomation);
deleteRecordingBt.addEventListener("click", deleteLastRecording);
speedSlider.addEventListener("input", (e) => {
	speedValueEl.textContent = e.target.value;
})
addPointBtn.addEventListener("click", addPointRow);

if (toggleUsgBtn) {
	toggleUsgBtn.addEventListener("click", () => {
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
			} else {
				isUsgOn = !isUsgOn;
				alert(data.message);
			}
		}).finally(() => {
			toggleUsgBtn.disabled = false;
		});
	});
}

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

const callButton = document.getElementById("call-button");
const voiceSelect = document.getElementById("voice-select");
const statusLine = document.getElementById("status");

let call = null;

function setState(state, message) {
  callButton.dataset.state = state;
  callButton.setAttribute("aria-label", state === "idle" ? "Start the call" : "End the call");
  voiceSelect.disabled = state !== "idle";
  statusLine.textContent = message;
}

async function loadVoices() {
  const response = await fetch("voices");
  if (!response.ok) {
    setState("idle", "The voices could not be loaded. Is the server running?");
    return;
  }
  const { voices } = await response.json();
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice.voice_key;
    option.textContent = `${voice.presented_gender === "female" ? "Female" : "Male"}: ${voice.description}`;
    voiceSelect.append(option);
  }
  setState("idle", "Press the button to call.");
}

async function startCall() {
  setState("connecting", "Connecting…");
  const microphone = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule("audio-worklets.js");
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/conversation?voice=${encodeURIComponent(voiceSelect.value)}`);
  socket.binaryType = "arraybuffer";
  call = { microphone, audioContext, socket, capture: null, playback: null };

  socket.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      call.playback?.port.postMessage(event.data, [event.data]);
      return;
    }
    const message = JSON.parse(event.data);
    if (message.type === "conversation_started") {
      connectAudio(message.guest_audio_sample_rate_hz, message.agent_audio_sample_rate_hz);
      setState("live", "Connected. Go ahead and talk.");
    } else if (message.type === "guest_started_speaking") {
      // Barge-in: the guest is talking, so stop the agent at once.
      call.playback?.port.postMessage("clear");
    } else if (message.type === "error") {
      statusLine.textContent = message.detail;
    }
  };
  socket.onclose = (event) => {
    const reason = statusLine.textContent && callButton.dataset.state !== "live" ? statusLine.textContent : "Call ended.";
    endCall(event.code === 1000 || event.code === 1005 ? "Call ended." : reason);
  };
}

function connectAudio(guestSampleRate, agentSampleRate) {
  const { audioContext, microphone, socket } = call;
  const source = audioContext.createMediaStreamSource(microphone);
  call.capture = new AudioWorkletNode(audioContext, "guest-capture", { processorOptions: { targetSampleRate: guestSampleRate } });
  call.capture.port.onmessage = (event) => {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(event.data);
    }
  };
  source.connect(call.capture);
  call.playback = new AudioWorkletNode(audioContext, "agent-playback", {
    numberOfInputs: 0,
    outputChannelCount: [1],
    processorOptions: { sourceSampleRate: agentSampleRate },
  });
  call.playback.connect(audioContext.destination);
}

function endCall(message) {
  if (!call) {
    return;
  }
  const { microphone, audioContext, socket } = call;
  call = null;
  microphone.getTracks().forEach((track) => track.stop());
  audioContext.close();
  if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
    socket.close(1000);
  }
  setState("idle", message);
}

callButton.addEventListener("click", async () => {
  if (call) {
    endCall("Call ended.");
    return;
  }
  try {
    await startCall();
  } catch (error) {
    endCall("");
    setState("idle", error.name === "NotAllowedError" ? "Microphone access was blocked." : `Could not start the call: ${error.message}`);
  }
});

loadVoices();

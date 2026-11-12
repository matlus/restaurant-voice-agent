const callButton = document.getElementById("call-button");
const voiceSelect = document.getElementById("voice-select");
const statusLine = document.getElementById("status");

// The page is in exactly one of these states. "unavailable" means the voices could not be loaded; pressing the button
// tries again.
const CallState = Object.freeze({
  UNAVAILABLE: "unavailable",
  IDLE: "idle",
  CONNECTING: "connecting",
  LIVE: "live",
});

// The call in progress, or null. Every resource is recorded here the moment it is created, so ending the call at any
// step, including a failed start, releases whatever exists by then.
let call = null;

function setState(state, message) {
  callButton.dataset.state = state;
  callButton.setAttribute("aria-label", state === CallState.UNAVAILABLE ? "Load the voices again" : state === CallState.IDLE ? "Start the call" : "End the call");
  voiceSelect.disabled = state !== CallState.IDLE;
  statusLine.textContent = message;
}

async function loadVoices() {
  setState(CallState.UNAVAILABLE, "Loading voices…");
  let voices;
  try {
    const response = await fetch("voices");
    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }
    ({ voices } = await response.json());
  } catch {
    setState(CallState.UNAVAILABLE, "The voices could not be loaded. Is the server running? Press the button to try again.");
    return;
  }
  voiceSelect.replaceChildren();
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice.voice_key;
    option.textContent = `${voice.presented_gender === "female" ? "Female" : "Male"}: ${voice.description}`;
    voiceSelect.append(option);
  }
  setState(CallState.IDLE, "Press the button to call.");
}

async function startCall() {
  const thisCall = { microphone: null, audioContext: null, socket: null, capture: null, playback: null, serverMessage: null };
  call = thisCall;
  setState(CallState.CONNECTING, "Connecting… Press the button to cancel.");
  try {
    await connectCall(thisCall);
  } catch (error) {
    // Only this attempt is ended: if it was cancelled and another call started, that call is left alone.
    if (call === thisCall) {
      endCall(error.name === "NotAllowedError" ? "Microphone access was blocked." : `Could not start the call: ${error.message}`);
    } else {
      releaseCallResources(thisCall);
    }
  }
}

async function connectCall(thisCall) {
  thisCall.microphone = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  // The call may have been cancelled while the browser asked for the microphone; a resource that arrives after that is
  // released at once.
  if (call !== thisCall) {
    releaseCallResources(thisCall);
    return;
  }
  thisCall.audioContext = new AudioContext();
  await thisCall.audioContext.audioWorklet.addModule("audio-worklets.js");
  if (call !== thisCall) {
    releaseCallResources(thisCall);
    return;
  }
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/conversation?voice=${encodeURIComponent(voiceSelect.value)}`);
  socket.binaryType = "arraybuffer";
  thisCall.socket = socket;

  socket.onmessage = (event) => {
    if (call !== thisCall) {
      return;
    }
    if (event.data instanceof ArrayBuffer) {
      playAgentSpeech(thisCall, event.data);
      return;
    }
    const message = JSON.parse(event.data);
    if (message.type === "conversation_started") {
      connectAudio(thisCall, message.guest_audio_sample_rate_hz, message.agent_audio_sample_rate_hz);
      setState(CallState.LIVE, "Connected. Go ahead and talk.");
    } else if (message.type === "guest_started_speaking") {
      // Barge-in: the guest is talking, so stop the agent at once.
      thisCall.playback?.port.postMessage("clear");
    } else if (message.type === "call_limit_reached" || message.type === "error") {
      // Shown when the socket closes, whatever state the call was in, so a failure is never reported as a hang-up.
      thisCall.serverMessage = message.detail;
    }
  };
  socket.onclose = (event) => {
    if (call !== thisCall) {
      return;
    }
    const isNormalClose = event.code === 1000 || event.code === 1005;
    endCall(thisCall.serverMessage ?? (isNormalClose ? "Call ended." : "The call was cut off. Please try again."));
  };
}

// The agent's speech is turned into samples here rather than on the audio thread, which must not stall.
function playAgentSpeech(thisCall, pcmBuffer) {
  if (!thisCall.playback) {
    return;
  }
  // A stray odd byte cannot hold a sample, so it is left off rather than failing the whole frame.
  const pcm = new Int16Array(pcmBuffer, 0, Math.floor(pcmBuffer.byteLength / Int16Array.BYTES_PER_ELEMENT));
  const samples = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i += 1) {
    samples[i] = pcm[i] / 0x8000;
  }
  thisCall.playback.port.postMessage(samples, [samples.buffer]);
}

function connectAudio(thisCall, guestSampleRate, agentSampleRate) {
  const { audioContext, microphone, socket } = thisCall;
  const source = audioContext.createMediaStreamSource(microphone);
  thisCall.capture = new AudioWorkletNode(audioContext, "guest-capture", { processorOptions: { targetSampleRate: guestSampleRate } });
  thisCall.capture.port.onmessage = (event) => {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(event.data);
    }
  };
  source.connect(thisCall.capture);
  thisCall.playback = new AudioWorkletNode(audioContext, "agent-playback", {
    numberOfInputs: 0,
    outputChannelCount: [1],
    processorOptions: { sourceSampleRate: agentSampleRate },
  });
  thisCall.playback.connect(audioContext.destination);
  // The agent's speech arrives faster than it plays. When it is cut off, the server must learn how much the guest never
  // heard, so the agent does not believe the guest heard it all.
  thisCall.playback.port.onmessage = (event) => {
    const { unplayedMilliseconds } = event.data;
    if (unplayedMilliseconds > 0 && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "agent_speech_cut_off", unplayed_milliseconds: unplayedMilliseconds }));
    }
  };
}

function releaseCallResources(thisCall) {
  thisCall.microphone?.getTracks().forEach((track) => track.stop());
  if (thisCall.audioContext && thisCall.audioContext.state !== "closed") {
    thisCall.audioContext.close();
  }
  const socket = thisCall.socket;
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    socket.close(1000);
  }
}

function endCall(message) {
  if (!call) {
    return;
  }
  const endedCall = call;
  call = null;
  releaseCallResources(endedCall);
  setState(CallState.IDLE, message);
}

callButton.addEventListener("click", async () => {
  if (callButton.dataset.state === CallState.UNAVAILABLE) {
    await loadVoices();
    return;
  }
  // While connecting or live, the button ends the call; while connecting, that cancels it.
  if (call) {
    endCall("Call ended.");
    return;
  }
  await startCall();
});

loadVoices();

// Runs on the audio thread. Capture turns microphone samples into 16-bit PCM at the rate the agent expects;
// playback plays the agent's speech, already turned into samples on the page, and can drop everything queued when the
// guest talks, saying how much it dropped.

// Far longer than any reply; past it, newly arriving speech is dropped rather than held without limit.
const MAXIMUM_QUEUED_SECONDS = 120;

class GuestCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetSampleRate = options.processorOptions.targetSampleRate;
    this.sourceStep = sampleRate / this.targetSampleRate;
    this.sourcePosition = 0;
    this.previousSample = 0;
    this.pending = [];
    this.chunkSampleCount = Math.round(this.targetSampleRate * 0.05);
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) {
      return true;
    }
    // Linear interpolation from the device rate down to the target rate.
    while (this.sourcePosition < channel.length) {
      const index = Math.floor(this.sourcePosition);
      const fraction = this.sourcePosition - index;
      const before = index === 0 ? this.previousSample : channel[index - 1];
      const after = channel[index];
      this.pending.push(before + (after - before) * fraction);
      this.sourcePosition += this.sourceStep;
    }
    this.sourcePosition -= channel.length;
    this.previousSample = channel[channel.length - 1];
    if (this.pending.length >= this.chunkSampleCount) {
      const pcm = new Int16Array(this.pending.length);
      for (let i = 0; i < this.pending.length; i += 1) {
        const clamped = Math.max(-1, Math.min(1, this.pending[i]));
        pcm[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      }
      this.pending = [];
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

class AgentPlaybackProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.sourceSampleRate = options.processorOptions.sourceSampleRate;
    this.sourceStep = this.sourceSampleRate / sampleRate;
    this.maximumQueuedSamples = MAXIMUM_QUEUED_SECONDS * this.sourceSampleRate;
    this.queue = [];
    this.queuedSamples = 0;
    // Speech dropped because the queue was full; the guest never hears it, so it counts as unplayed.
    this.droppedSamples = 0;
    this.current = null;
    this.position = 0;
    this.port.onmessage = (event) => {
      if (event.data === "clear") {
        this.port.postMessage({ unplayedMilliseconds: this.countUnplayedMilliseconds() });
        this.queue = [];
        this.queuedSamples = 0;
        this.droppedSamples = 0;
        this.current = null;
        this.position = 0;
        return;
      }
      const samples = event.data;
      if (this.queuedSamples + samples.length > this.maximumQueuedSamples) {
        this.droppedSamples += samples.length;
        return;
      }
      this.queue.push(samples);
      this.queuedSamples += samples.length;
    };
  }

  // How much speech the guest has not heard yet, at the agent's own sample rate.
  countUnplayedMilliseconds() {
    const unplayedCurrentSamples = this.current ? Math.max(0, this.current.length - this.position) : 0;
    const unplayedSamples = unplayedCurrentSamples + this.queuedSamples + this.droppedSamples;
    return Math.round((unplayedSamples / this.sourceSampleRate) * 1000);
  }

  process(_inputs, outputs) {
    const output = outputs[0][0];
    for (let i = 0; i < output.length; i += 1) {
      if (!this.current || this.position >= this.current.length - 1) {
        if (this.current) {
          this.position -= this.current.length - 1;
        }
        this.current = this.queue.shift() || null;
        if (this.current) {
          this.queuedSamples -= this.current.length;
        }
        if (!this.current) {
          this.position = 0;
          output.fill(0, i);
          return true;
        }
      }
      const index = Math.floor(this.position);
      const fraction = this.position - index;
      const before = this.current[index];
      const after = this.current[index + 1] ?? before;
      output[i] = before + (after - before) * fraction;
      this.position += this.sourceStep;
    }
    return true;
  }
}

registerProcessor("guest-capture", GuestCaptureProcessor);
registerProcessor("agent-playback", AgentPlaybackProcessor);

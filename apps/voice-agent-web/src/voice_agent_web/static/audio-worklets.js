// Runs on the audio thread. Capture turns microphone samples into 16-bit PCM at the rate the agent expects;
// playback turns the agent's 16-bit PCM back into samples and can drop everything queued when the guest talks,
// saying how much it dropped.

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
    this.queue = [];
    this.current = null;
    this.position = 0;
    this.port.onmessage = (event) => {
      if (event.data === "clear") {
        this.port.postMessage({ unplayedMilliseconds: this.countUnplayedMilliseconds() });
        this.queue = [];
        this.current = null;
        this.position = 0;
        return;
      }
      const pcm = new Int16Array(event.data);
      const samples = new Float32Array(pcm.length);
      for (let i = 0; i < pcm.length; i += 1) {
        samples[i] = pcm[i] / 0x8000;
      }
      this.queue.push(samples);
    };
  }

  // How much queued speech has not been played yet, at the agent's own sample rate.
  countUnplayedMilliseconds() {
    let unplayedSamples = this.current ? Math.max(0, this.current.length - this.position) : 0;
    for (const samples of this.queue) {
      unplayedSamples += samples.length;
    }
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

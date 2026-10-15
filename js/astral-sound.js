/* MaC Memory Archive hover cue; pentatonic other cues with matching MaC gain levels. */
(function (root) {
  function createSound(AudioContextClass) {
    let context;
    let enabled = false;
    const voices = new Set();
    const notes = {
      hover: [2349.3], select: [293.66, 440], reveal: [293.66, 392, 587.33],
      open: [392, 440], close: [440, 293.66],
    };
    function scroll() {
      // Soft cloth/paper unrolling, retaining the MaC hover's 0.04 peak.
      // Synthetic, in the same AudioContext; no downloaded audio or autoplay.
      if (!context.createBuffer || !context.createBufferSource || !context.createBiquadFilter) return false;
      while (voices.size >= 24) {
        const oldest=voices.values().next().value;
        oldest.gain.disconnect();
        try { oldest.oscillator.stop(); } catch (_) {}
        voices.delete(oldest);
      }
      try {
        const duration=2.8, now=context.currentTime;
        const buffer=context.createBuffer(1,Math.ceil(context.sampleRate*duration),context.sampleRate);
        const samples=buffer.getChannelData(0);
        let seed=1729;
        for (let i=0;i<samples.length;i++) {
          seed=(Math.imul(seed,1664525)+1013904223)|0;
          samples[i]=((seed>>>0)/2147483648-1)*(.8+.2*Math.sin(i/context.sampleRate*2*Math.PI*19));
        }
        const source=context.createBufferSource(), filter=context.createBiquadFilter(), gain=context.createGain();
        source.buffer=buffer;
        filter.type='lowpass'; filter.frequency.setValueAtTime(950,now); filter.Q.setValueAtTime(.5,now);
        gain.gain.setValueAtTime(.0001,now);
        gain.gain.exponentialRampToValueAtTime(.025,now+.12);
        gain.gain.exponentialRampToValueAtTime(.04,now+.65);
        gain.gain.exponentialRampToValueAtTime(.022,now+1.5);
        gain.gain.exponentialRampToValueAtTime(.012,now+2.3);
        gain.gain.exponentialRampToValueAtTime(.0001,now+duration);
        source.connect(filter); filter.connect(gain); gain.connect(context.destination);
        const voice={oscillator:source,gain,kind:'scroll'}; voices.add(voice);
        source.onended=()=> { source.disconnect(); filter.disconnect(); gain.disconnect(); voices.delete(voice); };
        source.start(now); source.stop(now+duration+.005);
        return true;
      } catch (_) { return false; }
    }
    function disable() {
      enabled = false;
      for (const voice of voices) {
        voice.gain.disconnect();
        try { voice.oscillator.stop(); } catch (_) { /* Already ended. */ }
      }
      voices.clear();
    }
    return {
      get enabled() { return enabled; },
      get supported() { return Boolean(AudioContextClass); },
      stop(kind) {
        for (const voice of voices) {
          if (voice.kind!==kind) continue;
          voice.gain.disconnect();
          try { voice.oscillator.stop(); } catch (_) {}
          voices.delete(voice);
        }
      },
      async enable() {
        if (!AudioContextClass) return false;
        try {
          context ||= new AudioContextClass();
          enabled = true;
          if (context.state === 'suspended') await context.resume();
          if (context.state !== 'running') disable();
        } catch (_) { disable(); }
        return enabled;
      },
      disable,
      play(kind) {
        if (kind==='scroll') return enabled && context?.state==='running' ? scroll() : false;
        if (!enabled || !context || context.state !== 'running' || !notes[kind]) return false;
        const now = context.currentTime;
        // No hover cooldown: every new card gets an immediate cue, like MaC.
        // Recycle the oldest voice at capacity instead of dropping new cues.
        while (voices.size + notes[kind].length > 24) {
          const oldest = [...voices].find(voice => voice.kind === 'hover') || voices.values().next().value;
          oldest.gain.disconnect();
          try { oldest.oscillator.stop(); } catch (_) { /* Already ended. */ }
          voices.delete(oldest);
        }
        try {
          notes[kind].forEach((frequency, index) => {
            const oscillator = context.createOscillator();
            const gain = context.createGain();
            const start = now + index * (kind === 'reveal' ? 0.045 : 0.038);
            const duration = kind === 'hover' ? 0.05 : kind === 'reveal' ? 1.25 : kind === 'close' ? 0.24 : 0.18;
            oscillator.type = 'sine';
            oscillator.frequency.setValueAtTime(frequency, start);
            if (kind === 'hover') oscillator.frequency.exponentialRampToValueAtTime(1760, start + 0.05);
            // Gain/envelopes measured from mac.ai.kr Memory Archive source.
            const peak = kind === 'hover' ? 0.04 : kind === 'reveal' ? 0.08 / (index + 1) : kind === 'close' ? 0.06 : 0.075;
            gain.gain.setValueAtTime(kind === 'reveal' ? 0.0001 : peak, start);
            if (kind === 'reveal') gain.gain.exponentialRampToValueAtTime(peak, start + 0.06);
            gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
            oscillator.connect(gain);
            gain.connect(context.destination);
            const voice = { oscillator, gain, kind };
            voices.add(voice);
            oscillator.onended = () => {
              oscillator.disconnect();
              gain.disconnect();
              voices.delete(voice);
            };
            oscillator.start(start);
            oscillator.stop(start + duration + (kind === 'hover' ? 0.002 : 0.005));
          });
          return true;
        } catch (_) { return false; }
      },
    };
  }
  if (typeof module === 'object' && module.exports) module.exports = { createSound };
  else root.AstralSound = { createSound };
})(typeof window === 'object' ? window : globalThis);

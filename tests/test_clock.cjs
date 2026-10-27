const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// Optional real-GSAP regression; otherwise emulate its six-decimal proxy updates.
const gsap = process.env.VIBE_GSAP ? require(process.env.VIBE_GSAP).gsap : {
  timeline() {
    return {
      to(clock, options) { this.clock = clock; this.options = options; return this; },
      render(t) { this.clock.t = Math.round(t * 1e6) / 1e6; return this; },
      totalTime(t, suppress) { this.render(t); if (!suppress) this.options.onUpdate(); return this; }
    };
  }
};
global.window = { gsap };
vm.runInThisContext(fs.readFileSync(path.join(__dirname, '..', 'assets', 'hyperframes-clock.js'), 'utf8'));
let rendered;
const { timeline, seek } = window.createVibeTimeline({ id: 'fixture', duration: 38.4, fps: 30, paint: t => { rendered = t; } });
for (const frame of [0, 64, 159, 255, 319, 335, 350, 446, 542, 638, 734, 798, 862, 913, 958, 1056, 1151]) {
  timeline.totalTime(frame / 30, true);
  assert.ok(Math.abs(rendered - frame / 30) < 1e-8, `Frame ${frame} slipped: ${rendered}`);
}
seek(.123456); assert.equal(rendered, .123456);
seek(319 / 30); const first = rendered; seek(35.1); seek(319 / 30); assert.equal(rendered, first);
seek(38.4); assert.ok(rendered < 38.4 && rendered > 38.39);
if (gsap.ticker) gsap.ticker.sleep();
console.log('17 cue boundaries, suppressed callbacks, random seeks and continuous preview passed.');

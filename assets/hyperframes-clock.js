/* Original reusable HyperFrames clock. The caller supplies a pure paint(time). */
(function (global) {
  'use strict';
  global.createVibeTimeline = function ({ id, duration, fps = 30, paint }) {
    if (!id || !(duration > 0) || !(fps > 0) || typeof paint !== 'function') {
      throw new Error('id, positive duration/fps, and paint(time) are required');
    }
    const clock = { t: 0 };
    const draw = raw => {
      const nearest = Math.round(raw * fps) / fps;
      const precise = Math.abs(raw - nearest) < 1e-5 ? nearest : raw;
      const t = Math.max(0, Math.min(duration - 1e-7, precise));
      paint(t);
      return t;
    };
    const timeline = global.gsap.timeline({ paused: true });
    timeline.to(clock, { t: duration, duration, ease: 'none', lazy: false, onUpdate: () => draw(clock.t) }, 0);
    const originalRender = timeline.render;
    timeline.render = function (...args) {
      const result = originalRender.apply(this, args);
      draw(clock.t);
      return result;
    };
    global.__timelines = global.__timelines || {};
    global.__timelines[id] = timeline;
    const seek = t => {
      const value = Math.max(0, Math.min(duration, t));
      timeline.totalTime(value, false);
      draw(value);
    };
    draw(0);
    return { timeline, seek, draw };
  };
})(window);

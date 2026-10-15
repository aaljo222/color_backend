/* Intro presentation only. No personal data, API calls, or image generation. */
(function () {
  'use strict';
  const painting = document.getElementById('heroPainting');
  const replay = document.getElementById('replayHeroPainting');
  const start = document.getElementById('heroStartButton');
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!painting || !replay || !start) return;
  // A refreshed report starts a new visit; keep the opening artwork in view.
  if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
  let visitorInteracted = false;
  ['pointerdown','wheel','touchstart','keydown'].forEach(type => {
    window.addEventListener(type, () => { visitorInteracted = true; }, {once:true, passive:true});
  });
  const showIntroFirst = () => {
    if (!visitorInteracted) window.scrollTo({top:0, behavior:'instant'});
  };
  if (document.readyState === 'complete') showIntroFirst();
  else window.addEventListener('load', showIntroFirst, {once:true});

  function syncMotion() {
    replay.hidden = motion.matches;
    painting.dataset.reveal = motion.matches ? 'static' : 'on';
  }
  function drawAgain() {
    if (motion.matches) return;
    painting.dataset.reveal = 'off';
    // Restart only the artwork reveal, never the form or calculated results.
    void painting.getBoundingClientRect();
    painting.dataset.reveal = 'on';
  }
  replay.addEventListener('click', drawAgain);
  painting.querySelector('image')?.addEventListener('load', drawAgain, {once:true});
  motion.addEventListener('change', syncMotion);
  syncMotion();

  start.addEventListener('click', event => {
    event.preventDefault();
    document.getElementById('birthSection').scrollIntoView({behavior:motion.matches ? 'instant' : 'smooth', block:'start'});
    document.getElementById('birthName')?.focus({preventScroll:true});
  });
}());

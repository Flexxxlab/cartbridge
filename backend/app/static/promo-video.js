// Promo "quick peek" player. Poster first, lazy-loaded, muted loop only while on screen, unmute button.
// Click/tap (or Enter/Space) plays it in place from 0 with sound and a minimal control bar; the expand
// button goes real fullscreen. Only one video has sound at a time. No overlay, no lightbox.
// Honours prefers-reduced-motion and Save-Data (poster only, no autoplay, no preload).
(() => {
  'use strict';
  const players = document.querySelectorAll('[data-promo-player]');
  if (!players.length) return;

  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const saveData = Boolean(navigator.connection && navigator.connection.saveData);
  const instances = [];
  const syncAll = () => instances.forEach((i) => i.sync());

  const svg = (d) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  const ICON_OFF = svg('<path d="M11 5 6 9H3v6h3l5 4z"/><path d="m22 9-6 6M16 9l6 6"/>');
  const ICON_ON = svg('<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>');
  const ICON_EXPAND = svg('<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>');

  const fsElement = () => document.fullscreenElement || document.webkitFullscreenElement || null;

  const init = (root) => {
    const frame = root.querySelector('.promo-frame') || root;
    const video = root.querySelector('.promo-video');
    const openBtn = root.querySelector('.promo-open');
    const muteBtn = root.querySelector('.promo-mute');
    const src = root.dataset.src;
    const title = root.dataset.title || 'Promo video';
    const product = root.dataset.product || title.replace(/\s+(quick peek|promo|demo)\b.*$/i, '');
    if (!video || !src) return;
    // Frameworks that render the page (React SSR) can drop the muted attribute; autoplay needs it.
    video.defaultMuted = true;
    video.muted = true;
    video.loop = true;
    let loaded = false;
    let visible = false;
    let engaged = false;
    let fsExitAt = 0;
    const openLabel = openBtn ? openBtn.getAttribute('aria-label') : '';
    const staticOnly = () => reduce.matches || saveData;

    const load = (force) => {
      if (loaded || (!force && staticOnly())) return;
      loaded = true;
      video.src = src;
      video.load();
    };

    // Expand button (next to the mute button) and a progress bar, shown while playing with sound.
    const expandBtn = document.createElement('button');
    expandBtn.type = 'button';
    expandBtn.className = 'promo-expand';
    expandBtn.setAttribute('aria-label', 'Watch ' + product + ' fullscreen');
    expandBtn.innerHTML = ICON_EXPAND;
    frame.append(expandBtn);
    const bar = document.createElement('input');
    bar.type = 'range';
    bar.className = 'promo-progress';
    bar.min = '0';
    bar.max = '1000';
    bar.value = '0';
    bar.step = '1';
    bar.setAttribute('aria-label', 'Seek ' + product + ' video');
    frame.append(bar);

    const paintState = () => {
      root.classList.toggle('is-engaged', engaged);
      root.classList.toggle('is-live', engaged && !video.paused);
      if (openBtn && openLabel) {
        openBtn.setAttribute('aria-label', engaged ? (video.paused ? 'Play ' : 'Pause ') + product + ' video' : openLabel);
      }
    };

    const sync = () => {
      root.classList.toggle('is-static', staticOnly());
      if (!loaded) return;
      const full = fsElement() === frame || fsElement() === root;
      if (engaged) {
        // Playing with sound: leaving the screen pauses it and it is not auto-resumed.
        // (Right after leaving fullscreen the layout is still settling, so ignore it briefly.)
        if (Date.now() - fsExitAt < 800) return;
        if ((!visible || document.hidden) && !full && !video.paused) video.pause();
        return;
      }
      const want = visible && !staticOnly() && !document.hidden;
      if (want) {
        const p = video.play();
        if (p && p.catch) p.catch(() => {});
      } else {
        video.pause();
      }
    };

    const preview = () => {
      engaged = false;
      video.loop = true;
      video.muted = true;
      paintState();
    };

    // Called when another video takes the sound: back to a silent preview.
    const release = () => {
      if (!engaged && video.muted) return;
      preview();
      sync();
    };
    const claim = () => instances.forEach((i) => { if (i.root !== root) i.release(); });

    const engage = (restart) => {
      load(true);
      claim();
      engaged = true;
      video.loop = false;
      video.muted = false;
      if (restart) {
        try { video.currentTime = 0; } catch (e) { /* metadata not ready; starts at 0 anyway */ }
      }
      paintState();
      const p = video.play();
      if (p && p.catch) p.catch(() => {});
    };

    if (muteBtn) {
      const paint = () => {
        muteBtn.innerHTML = video.muted ? ICON_OFF : ICON_ON;
        muteBtn.setAttribute('aria-label', video.muted ? 'Turn sound on' : 'Turn sound off');
      };
      paint();
      video.addEventListener('volumechange', paint);
      muteBtn.addEventListener('click', () => {
        video.muted = !video.muted;
        if (!video.muted) claim();
      });
    }

    if (openBtn) {
      openBtn.addEventListener('click', () => {
        if (!engaged) { engage(true); return; }
        if (video.paused) {
          const p = video.play();
          if (p && p.catch) p.catch(() => {});
        } else {
          video.pause();
        }
      });
    }

    expandBtn.addEventListener('click', () => {
      if (!engaged) engage(true);
      else { video.muted = false; claim(); video.play().catch(() => {}); }
      const req = frame.requestFullscreen || frame.webkitRequestFullscreen;
      if (req) {
        const r = req.call(frame);
        if (r && r.catch) r.catch(() => {});
      } else if (video.webkitEnterFullscreen) {
        video.webkitEnterFullscreen();
      }
    });

    video.addEventListener('play', paintState);
    video.addEventListener('pause', paintState);
    video.addEventListener('ended', () => {
      // Finished: back to the muted loop preview.
      preview();
      video.currentTime = 0;
      sync();
    });
    video.addEventListener('timeupdate', () => {
      if (engaged && video.duration) bar.value = String(Math.round((video.currentTime / video.duration) * 1000));
    });
    bar.addEventListener('input', () => {
      if (video.duration) video.currentTime = (Number(bar.value) / 1000) * video.duration;
    });

    document.addEventListener('fullscreenchange', () => {
      if (!fsElement()) { fsExitAt = Date.now(); setTimeout(sync, 900); }
    });
    document.addEventListener('webkitfullscreenchange', () => {
      if (!fsElement()) { fsExitAt = Date.now(); setTimeout(sync, 900); }
    });

    instances.push({ root, sync, release });

    if ('IntersectionObserver' in window) {
      new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) load();
        sync();
      }, { rootMargin: '300px 0px' }).observe(root);
      new IntersectionObserver((entries) => {
        visible = entries[entries.length - 1].intersectionRatio >= 0.5;
        if (visible) load();
        sync();
      }, { threshold: [0, 0.5, 1] }).observe(root);
    }
  };

  players.forEach(init);
  document.addEventListener('visibilitychange', syncAll);
  document.addEventListener('fullscreenchange', syncAll);
  document.addEventListener('webkitfullscreenchange', syncAll);
  const onMotion = () => syncAll();
  if (reduce.addEventListener) reduce.addEventListener('change', onMotion);
  syncAll();
})();

// Promo "quick peek" player. Poster first, lazy-loaded, muted loop only while on screen,
// unmute button, click/tap opens a full player (<dialog>) with controls.
// Honours prefers-reduced-motion and Save-Data (poster only, no autoplay, no preload).
(() => {
  'use strict';
  const players = document.querySelectorAll('[data-promo-player]');
  if (!players.length) return;

  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const saveData = Boolean(navigator.connection && navigator.connection.saveData);
  const syncers = [];
  let modalOpen = false;
  const syncAll = () => syncers.forEach((fn) => fn());

  const ICON_OFF = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="m22 9-6 6M16 9l6 6"/></svg>';
  const ICON_ON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>';

  const init = (root) => {
    const video = root.querySelector('.promo-video');
    const openBtn = root.querySelector('.promo-open');
    const muteBtn = root.querySelector('.promo-mute');
    const src = root.dataset.src;
    const title = root.dataset.title || 'Promo video';
    const ratio = root.dataset.ratio || '1.7778';
    if (!video || !src) return;
    // Frameworks that render the page (React SSR) can drop the muted attribute; autoplay needs it.
    video.defaultMuted = true;
    video.muted = true;
    let loaded = false;
    let visible = false;
    const staticOnly = () => reduce.matches || saveData;

    const load = () => {
      if (loaded || staticOnly()) return;
      loaded = true;
      video.src = src;
      video.load();
    };

    const sync = () => {
      root.classList.toggle('is-static', staticOnly());
      if (!loaded) return;
      const want = visible && !staticOnly() && !modalOpen && !document.hidden;
      if (want) {
        const p = video.play();
        if (p && p.catch) p.catch(() => {});
      } else {
        video.pause();
      }
    };
    syncers.push(sync);

    if (muteBtn) {
      const paint = () => {
        muteBtn.innerHTML = video.muted ? ICON_OFF : ICON_ON;
        muteBtn.setAttribute('aria-label', video.muted ? 'Turn sound on' : 'Turn sound off');
      };
      paint();
      muteBtn.addEventListener('click', () => {
        video.muted = !video.muted;
        paint();
      });
    }

    const openFull = () => {
      const dlg = document.createElement('dialog');
      dlg.className = 'promo-dialog';
      dlg.setAttribute('aria-label', title);
      dlg.style.setProperty('--pv-ratio', ratio);
      dlg.innerHTML = '<div class="promo-dialog-inner"><video controls playsinline></video>' +
        '<button class="promo-close" type="button" aria-label="Close video">×</button></div>';
      const full = dlg.querySelector('video');
      full.setAttribute('aria-label', title);
      full.poster = video.getAttribute('poster') || '';
      full.src = src;
      dlg.querySelector('.promo-close').addEventListener('click', () => dlg.close());
      dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
      dlg.addEventListener('close', () => {
        full.pause();
        full.removeAttribute('src');
        full.load();
        dlg.remove();
        modalOpen = false;
        syncAll();
        openBtn.focus();
      });
      document.body.append(dlg);
      modalOpen = true;
      syncAll();
      dlg.showModal();
      const p = full.play();
      if (p && p.catch) p.catch(() => {});
    };
    if (openBtn) openBtn.addEventListener('click', openFull);

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
  const onMotion = () => syncAll();
  if (reduce.addEventListener) reduce.addEventListener('change', onMotion);
  syncAll();
})();

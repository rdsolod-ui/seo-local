'use strict';
// Progressive enhancement: content stays readable if GSAP cannot load.
(() => {
  if (!window.gsap) return;
  const media = gsap.matchMedia();
  media.add('(prefers-reduced-motion: no-preference)', context => {
    const intro = gsap.timeline({defaults:{ease:'power3.out'}});
    intro.from('.hero-line', {yPercent:108, rotation:3, duration:1.05, stagger:.13}, .08)
      .from('.eyebrow .status-dot', {scale:0, duration:.45}, .15)
      .from('.hero-description, .hero-actions', {y:22, opacity:0, duration:.7, stagger:.12}, .6)
      .from('.scanner', {scale:.8, rotation:-12, opacity:0, duration:1.3, clearProps:'transform,opacity'}, .2)
      .from('.orbit-a, .orbit-b, .orbit-c', {rotation:100, scale:.65, duration:1.7, stagger:.1}, .25)
      .from('.scan-tag', {y:18, opacity:0, duration:.7, stagger:.12}, .9)
      .fromTo('.scan-beam', {y:-100, opacity:0}, {y:100, opacity:.65, duration:1, ease:'power1.inOut'}, .8)
      .to('.scan-beam', {opacity:0, duration:.35}, 1.8);
    const seen = new WeakSet();
    context.add('reveal', element => {
      if (seen.has(element)) return;
      seen.add(element);
      gsap.from(element, {y:26, opacity:0, duration:.7, clearProps:'transform,opacity', ease:'power3.out'});
    });
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        context.reveal(entry.target); observer.unobserve(entry.target);
      }
    }, {threshold:.15});
    document.querySelectorAll('.chapter-heading').forEach(el => observer.observe(el));
    context.add('change', event => {
      const el = document.getElementById(event.detail);
      if (!el || el.hidden) return;
      gsap.killTweensOf(el);
      gsap.fromTo(el, {opacity:.5, y:10}, {opacity:1, y:0, duration:.32, clearProps:'transform,opacity'});
    });
    const onChange = event => context.change(event);
    document.addEventListener('seo:change', onChange);
    return () => { observer.disconnect(); document.removeEventListener('seo:change', onChange); };
  });
  window.addEventListener('pagehide', () => media.revert(), {once:true});
})();

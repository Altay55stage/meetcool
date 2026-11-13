/* Original welcome and scroll choreography, followed by the working planner. */
(() => {
  const root = document.documentElement;
  root.classList.add('motion-ready');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const intro = document.querySelector('#welcomeIntro');
  const stage = document.querySelector('.motion-stage');
  const seal = document.querySelector('.hero-seal');
  const title = document.querySelector('.hero-title');
  const subtitle = document.querySelector('.hero-subtitle');
  const orbit = document.querySelector('.orbit-scene');
  const menuButton = document.querySelector('#landingMenu');
  const menuPanel = document.querySelector('#landingMenuPanel');
  const cards = [...document.querySelectorAll('.stack-card')];
  const reveals = [...document.querySelectorAll('.landing .reveal')];
  const query = new URLSearchParams(location.search);
  const invitation = query.has('join') || query.has('meeting');
  const clamp = value => Math.max(0, Math.min(1, value));
  let frame = 0, timer, introComplete = false;
  function dismissIntro(immediate = false) {
    if (introComplete || !intro) return;
    introComplete = true;
    clearTimeout(timer);
    try { sessionStorage.setItem('meetcool-intro', 'seen'); } catch {}
    intro.classList.add('intro-finished');
    intro.inert = true;
    root.classList.remove('intro-running');
    if (immediate) intro.remove();
    else setTimeout(() => intro.remove(), 650);
  }
  let seen = false;
  try { seen = sessionStorage.getItem('meetcool-intro') === 'seen'; } catch {}
  if (intro) {
    if (seen || reducedMotion.matches || invitation) dismissIntro(true);
    else {
      root.classList.add('intro-running');
      intro.querySelectorAll('.intro-letter').forEach((letter, i) => letter.style.setProperty('--letter-index', i));
      intro.querySelector('.intro-skip')?.addEventListener('click', () => dismissIntro());
      timer = setTimeout(() => dismissIntro(), 2300);
    }
  }
  function closeMenu() {
    if (!menuPanel) return;
    menuPanel.hidden = true;
    menuButton?.setAttribute('aria-expanded', 'false');
  }
  menuButton?.addEventListener('click', () => {
    const opening = menuPanel.hidden;
    menuPanel.hidden = !opening;
    menuButton.setAttribute('aria-expanded', String(opening));
  });
  menuPanel?.querySelectorAll('a,button').forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (menuPanel && !menuPanel.hidden) { closeMenu(); menuButton?.focus(); }
    dismissIntro();
  });
  document.querySelectorAll('[data-open-planner]').forEach(button => button.addEventListener('click', e => {
    e.preventDefault();
    dismissIntro(true);
    closeMenu();
    document.dispatchEvent(new CustomEvent('planner:open', {detail:{target:button.dataset.openPlanner || 'explore'}}));
    requestAnimationFrame(() => document.querySelector('#planner')?.scrollIntoView({behavior:reducedMotion.matches?'instant':'smooth',block:'start'}));
  }));
  const observer = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      entry.target.classList.add('is-visible');
      observer.unobserve(entry.target);
    }
  }, {threshold:.12,rootMargin:'0px 0px -24px 0px'}) : null;
  reveals.forEach((el, i) => {
    el.style.setProperty('--reveal-delay', `${i % 3 * 80}ms`);
    if (reducedMotion.matches || !observer) el.classList.add('is-visible');
    else observer.observe(el);
  });
  function renderScroll() {
    frame = 0;
    if (document.hidden) return;
    if (reducedMotion.matches) {
      [seal,title,subtitle,orbit].forEach(el => { el?.style.removeProperty('transform'); el?.style.removeProperty('opacity'); });
      cards.forEach(card => {card.querySelector('.stack-visual')?.style.removeProperty('transform');card.querySelector('.stack-shade')?.style.removeProperty('opacity');});
      return;
    }
    if (stage) {
      const rect = stage.getBoundingClientRect();
      const progress = clamp(-rect.top / Math.max(1, rect.height - innerHeight));
      stage.style.setProperty('--scene-progress', progress.toFixed(4));
      const departure = clamp(progress / .4);
      if (seal) {seal.style.transform=`scale(${1-departure*.75}) rotate(${-departure*30}deg)`;seal.style.opacity=String(1-clamp(progress/.35));}
      for (const el of [title,subtitle]) if (el) {el.style.opacity=String(1-departure);el.style.transform=`translateY(${-departure*45}px)`;}
      if (orbit) {const arrival=clamp((progress-.15)/.4);orbit.style.opacity=String(arrival);orbit.style.transform=`translateY(${80*(1-arrival)}px) scale(${.8+arrival*.2})`;}
      stage.classList.toggle('scene-arrived', progress>.55);
    }
    cards.forEach((card, i) => {
      const next = cards[i+1];
      if (!next) return;
      const progress=clamp(1-next.getBoundingClientRect().top/Math.max(1,innerHeight));
      const visual=card.querySelector('.stack-visual'),shade=card.querySelector('.stack-shade');
      if (visual) visual.style.transform=`translateY(${-progress*3}%) scale(${1-progress*.1})`;
      if (shade) shade.style.opacity=String(progress*.35);
    });
  }
  function requestRender(){if(!frame)frame=requestAnimationFrame(renderScroll);}
  addEventListener('scroll',requestRender,{passive:true});
  addEventListener('resize',requestRender,{passive:true});
  reducedMotion.addEventListener('change',()=>{if(reducedMotion.matches){dismissIntro(true);reveals.forEach(el=>el.classList.add('is-visible'));}requestRender();});
  document.addEventListener('visibilitychange',()=>{root.classList.toggle('page-paused',document.hidden);if(!document.hidden)requestRender();});
  requestRender();
  if (invitation) {
    const jump=()=>document.querySelector('#planner')?.scrollIntoView({behavior:'instant',block:'start'});
    if(document.readyState==='complete')jump();else addEventListener('load',jump,{once:true});
  }
})();

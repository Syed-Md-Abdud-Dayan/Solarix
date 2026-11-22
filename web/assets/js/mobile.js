/* Hamburger drawer for the sidebar (phones & tablets). */
(function(){
  'use strict';
  const body=document.body, side=document.querySelector('.sidebar'), top=document.querySelector('.topbar');
  if(!side||!top) return;
  const btn=document.createElement('button');
  btn.type='button'; btn.className='menu-btn'; btn.setAttribute('aria-label','Open menu'); btn.setAttribute('aria-expanded','false'); btn.setAttribute('aria-controls','sidebar'); btn.innerHTML='<span></span>';
  const first=top.firstElementChild; first.insertBefore(btn,first.firstChild);
  side.id='sidebar';
  const scrim=document.createElement('div'); scrim.className='nav-scrim'; document.body.append(scrim);
  const close=document.createElement('button'); close.type='button'; close.className='drawer-close'; close.setAttribute('aria-label','Close menu'); close.textContent='✕'; side.prepend(close);
  const mq=window.matchMedia('(max-width:900px)');
  function set(open){ body.classList.toggle('nav-open',open); btn.setAttribute('aria-expanded',String(open)); btn.setAttribute('aria-label',open?'Close menu':'Open menu'); if(open) side.querySelector('.nav-link.active,.nav-link')?.focus({preventScroll:true}); else if(mq.matches) btn.focus({preventScroll:true}); }
  btn.addEventListener('click',()=>set(!body.classList.contains('nav-open')));
  scrim.addEventListener('click',()=>set(false)); close.addEventListener('click',()=>set(false));
  side.addEventListener('click',e=>{ if(e.target.closest('a.nav-link')&&mq.matches) set(false); });
  document.addEventListener('keydown',e=>{ if(e.key==='Escape'&&body.classList.contains('nav-open')) set(false); });
  mq.addEventListener('change',()=>{ if(!mq.matches) body.classList.remove('nav-open'); });
  // inert drawer links while closed on mobile so keyboard users don't tab into hidden items
  function sync(){ const hidden=mq.matches&&!body.classList.contains('nav-open'); side.toggleAttribute('inert',hidden); }
  new MutationObserver(sync).observe(body,{attributes:true,attributeFilter:['class']}); mq.addEventListener('change',sync); sync();
})();

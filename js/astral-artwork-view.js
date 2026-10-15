/* Local presentation only: never generates, recolors, or changes the PNG. */
(function(root) {
  function createArtworkView({document, motion, sound, openDialog, closeDialog, Observer=root.IntersectionObserver}) {
    const trigger=document.getElementById('artworkOpenButton');
    const reveal=document.getElementById('artworkReveal');
    const image=document.getElementById('artworkRevealImage');
    const sheet=document.getElementById('artworkScrollSheet');
    const hint=document.getElementById('artworkViewHint');
    const dialog=document.getElementById('artworkDialog');
    const large=document.getElementById('artworkDialogImage');
    let epoch=0, url=null, visible=false, closing=false, observer;
    let scrollLock;
    function lockScroll() {
      const body=document.body;
      if (!body || scrollLock) return;
      scrollLock={x:root.scrollX||0,y:root.scrollY||0,styles:{}};
      for (const key of ['position','top','left','width','overflow']) scrollLock.styles[key]=body.style[key];
      Object.assign(body.style,{position:'fixed',top:`-${scrollLock.y}px`,left:`-${scrollLock.x}px`,width:'100%',overflow:'hidden'});
    }
    function unlockScroll() {
      if (!scrollLock) return;
      const saved=scrollLock; scrollLock=null;
      Object.assign(document.body.style,saved.styles);
      root.scrollTo?.({left:saved.x,top:saved.y,behavior:'instant'});
      trigger.focus?.({preventScroll:true});
    }
    function finish() {
      if (!url) return;
      sound.stop('scroll');
      reveal.dataset.state='complete';
      sheet.removeAttribute('clip-path'); // Mount and artwork reveal together, pixels unchanged.
      trigger.disabled=false;
      reveal.getAnimations?.({subtree:true}).forEach(animation=>animation.cancel());
    }
    function start() {
      if (!url || !visible || document.hidden || reveal.dataset.state!=='waiting') return;
      observer?.unobserve(trigger);
      if (motion.matches) return finish();
      const token=epoch;
      reveal.dataset.state='unrolling';
      void reveal.getBoundingClientRect();
      const animations=reveal.getAnimations?.({subtree:true}) || [];
      if (!animations.length) return finish(); // Unsupported/CSS-off fallback.
      sound.play('scroll'); // Paper/cloth roll friction follows the falling roller.
      Promise.allSettled(animations.map(animation=>animation.finished)).then(()=> {
        if (epoch===token && reveal.dataset.state==='unrolling') finish();
      });
    }
    function schedule() {
      if (!url || !visible || document.hidden) return;
      if (observer) observer.observe(trigger); else start();
    }
    if (Observer) observer=new Observer(entries=> {
      if (entries.some(entry=>entry.isIntersecting && (entry.intersectionRatio>=.35 ||
          (entry.intersectionRect?.height||0)>=Math.min(160,(entry.rootBounds?.height||400)*.4)))) start();
    },{threshold:[0,.05,.1,.15,.2,.35]});
    function dismiss(event) {
      event?.preventDefault();
      if (!dialog.open || closing) return;
      closing=true;
      sound.play('close');
      Promise.resolve(closeDialog(dialog)).finally(()=> { closing=false; large.removeAttribute('src'); unlockScroll(); });
    }
    trigger.addEventListener('click',event=> {
      if (!url || trigger.disabled || closing || dialog.open) return;
      if (event.detail>0) {
        const bounds=image.getBoundingClientRect();
        if (event.clientX<bounds.left || event.clientX>bounds.right || event.clientY<bounds.top || event.clientY>bounds.bottom) return;
      }
      large.src=url;
      lockScroll();
      openDialog(dialog); // Existing MaC open cue and animation, unchanged levels.
    });
    dialog.addEventListener('click',dismiss); // Painting, modal surface and backdrop all close.
    dialog.addEventListener('cancel',dismiss); // Escape remains accessible.
    dialog.addEventListener('close',()=> { large.removeAttribute('src'); unlockScroll(); });
    motion.addEventListener('change',()=> { if (motion.matches) finish(); });
    document.addEventListener('visibilitychange',()=> {
      if (document.hidden && reveal.dataset.state==='unrolling') finish();
      else if (!document.hidden) schedule();
    });
    function reset() {
      epoch++;
      sound.stop('scroll');
      observer?.unobserve(trigger);
      url=null;
      reveal.dataset.state='waiting';
      reveal.getAnimations?.({subtree:true}).forEach(animation=>animation.cancel());
      trigger.hidden=true; trigger.disabled=true; hint.hidden=true;
      image.removeAttribute('href'); large.removeAttribute('src');
      if (dialog.open) dialog.close();
      unlockScroll();
    }
    return {
      reset,
      reveal(nextUrl) {
        reset(); url=nextUrl;
        image.setAttribute('href',url); sheet.setAttribute('clip-path','url(#artworkScrollClip)');
        trigger.hidden=false; hint.hidden=false;
        if (visible && !document.hidden) trigger.scrollIntoView?.({behavior:motion.matches?'instant':'smooth',block:'start'});
        schedule();
      },
      setVisible(value) {
        visible=value;
        if (value) schedule();
        else {
          observer?.unobserve(trigger);
          if (reveal.dataset.state==='unrolling') finish();
          if (dialog.open) dismiss();
        }
      },
    };
  }
  const api={createArtworkView};
  if (typeof module==='object' && module.exports) module.exports=api;
  else root.AstralArtworkView=api;
})(typeof window==='object'?window:globalThis);

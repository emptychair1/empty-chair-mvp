(()=>{
  const all=[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16];
  const masculine=[1,3,6,8,9,11,13,15];
  const feminine=[2,4,5,7,10,12,14,16];

  function hashName(name){
    name=String(name||'?');
    let h=2166136261;
    for(const ch of name){
      h^=ch.charCodeAt(0);
      h=Math.imul(h,16777619)>>>0;
    }
    return h>>>0;
  }

  function normalizedPresentation(value){
    const v=String(value||'').trim().toLowerCase();
    if(['male','man','masculine','m'].includes(v)) return 'masculine';
    if(['female','woman','feminine','f'].includes(v)) return 'feminine';
    return '';
  }

  function profileIndex(name,presentation){
    const explicit=normalizedPresentation(presentation);
    const pool=explicit==='masculine'?masculine:explicit==='feminine'?feminine:all;
    return pool[hashName(name)%pool.length];
  }

  function profilePath(name,presentation){
    const n=String(profileIndex(name,presentation)).padStart(2,'0');
    return `/static/profile-${n}.png?v=2`;
  }

  function hydrate(root=document){
    root.querySelectorAll('.mock-avatar,.person-avatar').forEach(el=>{
      const name=el.dataset.name||el.getAttribute('alt')||'?';
      const presentation=el.dataset.gender||el.dataset.presentation||'';
      el.src=profilePath(name,presentation);
    });
  }

  window.EmptyChairAvatar={
    svg:profilePath,
    src:profilePath,
    hydrate
  };
})();
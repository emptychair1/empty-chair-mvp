(()=>{
  function stableIndex(name){
    name=String(name||'?');
    let h=2166136261;
    for(const ch of name){
      h^=ch.charCodeAt(0);
      h=Math.imul(h,16777619)>>>0;
    }
    return (h%16)+1;
  }

  function profilePath(name){
    const n=String(stableIndex(name)).padStart(2,'0');
    return `/static/profile-${n}.png?v=1`;
  }

  window.EmptyChairAvatar={
    svg:profilePath,
    src:profilePath
  };
})();
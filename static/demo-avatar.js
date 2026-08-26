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
    return `/static/profile-${n}.png?v=3`;
  }

  function hydrate(root=document){
    root.querySelectorAll('.mock-avatar,.person-avatar').forEach(el=>{
      const name=el.dataset.name||el.getAttribute('alt')||'?';
      const presentation=el.dataset.gender||el.dataset.presentation||'';
      el.src=profilePath(name,presentation);
    });
  }

  function addAvatar(target,name,presentation=''){
    if(!target||target.dataset.avatarDecorated==='1') return;
    const clean=String(name||'').trim();
    if(!clean) return;
    target.dataset.avatarDecorated='1';
    const img=document.createElement('img');
    img.className='person-avatar auto-person-avatar';
    img.dataset.name=clean;
    if(presentation) img.dataset.presentation=presentation;
    img.alt='';
    img.src=profilePath(clean,presentation);
    const wrap=document.createElement('span');
    wrap.className='person-with-avatar';
    target.parentNode.insertBefore(wrap,target);
    wrap.appendChild(img);
    wrap.appendChild(target);
  }

  function decorate(root=document){
    root.querySelectorAll('.queue-name').forEach(el=>addAvatar(el,el.textContent));
    root.querySelectorAll('.live-person').forEach(el=>addAvatar(el,el.textContent.replace(/ chose this opening\.?$/i,'')));
    root.querySelectorAll('.match .name').forEach(el=>addAvatar(el,el.textContent));
    root.querySelectorAll('.rankrow>div:nth-child(2)>strong:first-child').forEach(el=>addAvatar(el,el.textContent));
    if(location.pathname==='/bookings'){
      root.querySelectorAll('table tbody tr').forEach(row=>{
        const cells=row.querySelectorAll('td');
        if(cells.length>=2){
          const cell=cells[1];
          if(!cell.querySelector('.person-avatar')&&cell.textContent.trim()&&!/No booking/i.test(cell.textContent)){
            const textNode=[...cell.childNodes].find(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim());
            if(textNode){
              const span=document.createElement('span');
              span.textContent=textNode.textContent.trim();
              cell.replaceChild(span,textNode);
              addAvatar(span,span.textContent);
            }
          }
        }
      });
    }
    hydrate(root);
  }

  function installStyles(){
    if(document.getElementById('empty-chair-avatar-styles')) return;
    const style=document.createElement('style');
    style.id='empty-chair-avatar-styles';
    style.textContent=`.person-with-avatar{display:inline-flex;align-items:center;gap:10px;min-width:0}.auto-person-avatar{width:42px;height:42px;border-radius:50%;border:1px solid var(--line,#3b3a32);object-fit:cover;flex:0 0 42px;background:#0b0d0b}.queue-name .auto-person-avatar{width:36px;height:36px}.rankrow .person-with-avatar,.match .person-with-avatar{display:flex}.live-person .person-with-avatar{display:flex}`;
    document.head.appendChild(style);
  }

  window.EmptyChairAvatar={svg:profilePath,src:profilePath,hydrate,decorate};
  const boot=()=>{installStyles();decorate(document)};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
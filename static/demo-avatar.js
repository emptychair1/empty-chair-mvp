(()=>{
  const masculine=[1,3,6,8,9,11,13,15];
  const feminine=[2,4,5,7,10,12,14];
  const neutral=16;
  const masculineNames=new Set(['aaron','adam','adrian','alexander','andrew','anthony','ben','benjamin','brandon','brian','bryan','caleb','cameron','charles','chris','christian','christopher','daniel','david','derek','dylan','eli','elijah','eric','ethan','evan','frank','gabriel','george','henry','ian','isaac','jack','jacob','jake','james','jason','jeff','jeremy','jesse','john','jonathan','jordan','jose','joseph','josh','joshua','justin','kevin','liam','logan','luke','mark','mason','matt','matthew','michael','mike','nathan','nicholas','noah','oliver','owen','patrick','paul','peter','ryan','samuel','scott','sean','steven','thomas','tim','tyler','william','zachary']);
  const feminineNames=new Set(['abigail','alexandra','alice','alyssa','amanda','amelia','amy','anna','ashley','audrey','ava','averie','brianna','brooke','caroline','charlotte','chloe','claire','danielle','ella','emily','emma','erin','eva','evelyn','gabriella','grace','hailey','hannah','isabella','jasmine','jennifer','jessica','julia','karen','katherine','katie','kayla','lauren','lena','lily','lucy','madeline','madison','maria','maya','megan','melissa','mia','michelle','natalie','nicole','olivia','rachel','rebecca','samantha','sarah','sophia','stephanie','taylor','victoria','zoe']);

  function hashName(name){
    name=String(name||'?');
    let h=2166136261;
    for(const ch of name){h^=ch.charCodeAt(0);h=Math.imul(h,16777619)>>>0;}
    return h>>>0;
  }

  function normalizedPresentation(value){
    const v=String(value||'').trim().toLowerCase();
    if(['male','man','masculine','m'].includes(v)) return 'masculine';
    if(['female','woman','feminine','f'].includes(v)) return 'feminine';
    if(['neutral','nonbinary','non-binary','genderless','unknown'].includes(v)) return 'neutral';
    return '';
  }

  function inferredPresentation(name){
    const first=String(name||'').trim().toLowerCase().split(/\s+/)[0].replace(/[^a-z'-]/g,'');
    if(masculineNames.has(first)) return 'masculine';
    if(feminineNames.has(first)) return 'feminine';
    return 'neutral';
  }

  function profileIndex(name,presentation){
    const explicit=normalizedPresentation(presentation);
    const inferred=explicit||inferredPresentation(name);
    if(inferred==='neutral') return neutral;
    const pool=inferred==='masculine'?masculine:feminine;
    return pool[hashName(name)%pool.length];
  }

  function profilePath(name,presentation){
    const n=String(profileIndex(name,presentation)).padStart(2,'0');
    return `/static/profile-${n}.png?v=5`;
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

  function decorateDashboard(root){
    root.querySelectorAll('.opening-artist').forEach(el=>addAvatar(el,el.textContent));
    root.querySelectorAll('.activity-main strong:first-child').forEach(el=>addAvatar(el,el.textContent));
    root.querySelectorAll('.live-opening h3').forEach(el=>{
      const name=el.textContent.split('·')[0].trim();
      if(name) addAvatar(el,name);
    });
    decorateDashboardCustomers(root);
  }

  async function decorateDashboardCustomers(root=document){
    const cards=[...root.querySelectorAll('.metric-card')];
    const customerCard=cards.find(card=>/customers ready/i.test(card.querySelector('.metric-label')?.textContent||''));
    if(!customerCard||customerCard.querySelector('.customer-avatar-strip')) return;

    const strip=document.createElement('div');
    strip.className='customer-avatar-strip';
    strip.setAttribute('aria-label','Customer profiles ready to match');
    customerCard.appendChild(strip);

    try{
      const response=await fetch('/customers',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok) throw new Error('customer list unavailable');
      const html=await response.text();
      const doc=new DOMParser().parseFromString(html,'text/html');
      const names=[...doc.querySelectorAll('.customer-avatar[data-name]')]
        .map(el=>el.dataset.name||'')
        .filter(Boolean)
        .slice(0,6);

      names.forEach(name=>{
        const img=document.createElement('img');
        img.className='dashboard-customer-avatar';
        img.dataset.name=name;
        img.alt='';
        img.src=profilePath(name);
        strip.appendChild(img);
      });

      if(names.length){
        const more=document.createElement('a');
        more.className='customer-avatar-more';
        more.href='/customers';
        more.textContent='View';
        strip.appendChild(more);
      }
    }catch(error){
      strip.remove();
    }
  }

  function decorateDemandGraph(root){
    root.querySelectorAll('.dg-card .dg-name').forEach(el=>{
      if(!/no customers/i.test(el.textContent)) addAvatar(el,el.textContent);
    });
  }

  function decorateOpenings(root){
    root.querySelectorAll('.campaign').forEach(card=>{
      const strong=card.querySelector(':scope > div > strong:first-child');
      if(strong && !/reached the customer|could not reach/i.test(strong.textContent)) addAvatar(strong,strong.textContent);
    });
  }

  function decorateConciergeLeads(root){
    root.querySelectorAll('.lead-card').forEach(card=>{
      const nameEl=card.querySelector('.lead-name');
      if(!nameEl) return;
      const name=nameEl.textContent.trim();
      let img=card.querySelector('.identity img.avatar,.identity img.mock-avatar,.identity img.person-avatar');
      if(!img){
        img=document.createElement('img');
        img.className='avatar mock-avatar person-avatar';
        const identity=card.querySelector('.identity');
        if(identity) identity.insertBefore(img,identity.firstChild);
      }
      if(img){
        img.classList.add('person-avatar');
        img.dataset.name=name;
        img.alt='';
        img.src=profilePath(name);
      }
    });
  }

  function decoratePlatform(root){
    root.querySelectorAll('.studio-row').forEach(row=>{
      if(row.querySelector('.platform-shop-avatar')) return;
      const title=row.querySelector('.studio-title');
      if(!title||!title.parentElement) return;
      const identity=document.createElement('div');
      identity.className='platform-studio-identity';
      const img=document.createElement('img');
      img.className='platform-shop-avatar';
      img.src='/static/shop-avatar.png?v=2';
      img.alt='';
      title.parentElement.insertBefore(identity,title);
      identity.appendChild(img);
      identity.appendChild(title);
      const owner=identity.nextElementSibling;
      if(owner&&owner.classList.contains('studio-owner')) identity.appendChild(owner);
    });
  }

  function decorate(root=document){
    root.querySelectorAll('.queue-name').forEach(el=>addAvatar(el,el.textContent));
    root.querySelectorAll('.live-person').forEach(el=>addAvatar(el,el.textContent.replace(/ chose this opening\.?$/i,'')));
    root.querySelectorAll('.match .name').forEach(el=>addAvatar(el,el.textContent));
    root.querySelectorAll('.rankrow>div:nth-child(2)>strong:first-child').forEach(el=>addAvatar(el,el.textContent));
    root.querySelectorAll('.artist-card .artist-name').forEach(el=>addAvatar(el,el.textContent));

    if(location.pathname==='/') decorateDashboard(root);
    if(location.pathname==='/demand-graph') decorateDemandGraph(root);
    if(location.pathname==='/pilot') decorateOpenings(root);
    if(location.pathname==='/concierge-leads') decorateConciergeLeads(root);
    if(location.pathname==='/owner') decoratePlatform(root);

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
    style.textContent=`
      .person-with-avatar{display:inline-flex;align-items:center;gap:10px;min-width:0}
      .auto-person-avatar{width:42px;height:42px;border-radius:50%;border:1px solid var(--line,#3b3a32);object-fit:cover;flex:0 0 42px;background:#0b0d0b}
      .queue-name .auto-person-avatar{width:36px;height:36px}
      .rankrow .person-with-avatar,.match .person-with-avatar,.dg-name .person-with-avatar,.opening-artist .person-with-avatar,.activity-main .person-with-avatar{display:flex}
      .live-person .person-with-avatar{display:flex}
      .customer-avatar-strip{display:flex;align-items:center;margin-top:10px;min-height:34px}
      .dashboard-customer-avatar{width:34px;height:34px;border-radius:50%;border:2px solid #0d0f0d;object-fit:cover;background:#0b0d0b;margin-left:-7px}
      .dashboard-customer-avatar:first-child{margin-left:0}
      .customer-avatar-more{margin-left:8px;color:var(--signal,#c7ff3e);font-size:9px;font-weight:850;text-transform:uppercase;text-decoration:none}
      .platform-studio-identity{display:grid;grid-template-columns:76px minmax(0,1fr);column-gap:14px;align-items:center;min-width:0}
      .platform-shop-avatar{grid-row:1 / span 2;width:76px;height:66px;object-fit:contain;display:block}
      .platform-studio-identity .studio-title,.platform-studio-identity .studio-owner{grid-column:2;margin-left:0}
      .lead-card .avatar{display:block!important;opacity:1!important}
      @media(max-width:700px){.platform-studio-identity{grid-template-columns:62px minmax(0,1fr)}.platform-shop-avatar{width:62px;height:56px}.dashboard-customer-avatar{width:31px;height:31px}}
    `;
    document.head.appendChild(style);
  }

  window.EmptyChairAvatar={svg:profilePath,src:profilePath,hydrate,decorate,infer:inferredPresentation};
  const boot=()=>{installStyles();decorate(document)};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();
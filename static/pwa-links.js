(()=>{
  const ensureLink=(rel,href,attrs={})=>{
    let link=document.head.querySelector(`link[rel="${rel}"]`);
    if(!link){link=document.createElement('link');link.rel=rel;document.head.appendChild(link);}
    link.href=href;
    Object.entries(attrs).forEach(([k,v])=>link.setAttribute(k,v));
  };
  ensureLink('manifest','/manifest.webmanifest?v=3');
  ensureLink('icon','/static/favicon.png?v=3',{type:'image/png',sizes:'32x32'});
  ensureLink('apple-touch-icon','/static/apple-touch-icon.png?v=3',{sizes:'180x180'});
  let theme=document.head.querySelector('meta[name="theme-color"]');
  if(!theme){theme=document.createElement('meta');theme.name='theme-color';document.head.appendChild(theme);}
  theme.content='#b1ff00';
  if('serviceWorker' in navigator){window.addEventListener('load',()=>{navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(()=>{});},{once:true});}

  const fixDashboardActions=()=>{
    if(location.pathname!=='/') return;
    const topbar=document.querySelector('.topbar');
    const actions=topbar?.querySelector('.top-actions');
    if(!topbar||!actions) return;
    if(!document.querySelector('link[data-dashboard-actions]')){
      const css=document.createElement('link');
      css.rel='stylesheet';
      css.href='/static/dashboard-top-actions.css?v=3';
      css.dataset.dashboardActions='1';
      document.head.appendChild(css);
    }
    topbar.classList.add('dashboard-topbar');
    actions.className='dashboard-top-actions';
    actions.innerHTML=`
      <a class="button primary-action" href="#create-opening">Add an Opening</a>
      <a class="button secondary" href="/demand-acquisition">Demand Engine</a>
      <a class="button secondary" href="/bookings">Calendar</a>`;
  };

  const addConsultationsInbox=()=>{
    const topbars=[...document.querySelectorAll('.topbar')];
    if(!topbars.length||document.querySelector('.ec-inbox-button')) return;
    if(!document.querySelector('style[data-ec-inbox]')){
      const style=document.createElement('style');
      style.dataset.ecInbox='1';
      style.textContent=`
        .ec-inbox-button{position:relative;display:grid;place-items:center;width:46px;height:46px;flex:0 0 46px;border:1px solid #3a4036;background:#0b0e0b;color:#f2ecde;text-decoration:none;box-shadow:2px 2px 0 #000;transition:.14s ease}
        .ec-inbox-button:hover{border-color:#c7ff3e;color:#c7ff3e;transform:translate(-1px,-1px);box-shadow:3px 3px 0 #000}
        .ec-inbox-button svg{width:22px;height:22px;display:block}
        .ec-inbox-badge{position:absolute;right:-6px;top:-6px;min-width:19px;height:19px;padding:0 5px;border-radius:999px;display:none;align-items:center;justify-content:center;background:#c7ff3e;color:#080908;border:2px solid #080908;font:900 10px ui-monospace,monospace;box-sizing:border-box}
        .ec-inbox-button.has-unread .ec-inbox-badge{display:flex}
        @media(max-width:610px){.ec-inbox-button{width:40px;height:40px;flex-basis:40px}.ec-inbox-button svg{width:20px;height:20px}}
      `;
      document.head.appendChild(style);
    }
    topbars.forEach(topbar=>{
      const actions=topbar.querySelector('.top-actions,.dashboard-top-actions');
      const button=document.createElement('a');
      button.className='ec-inbox-button';
      button.href='/consultations';
      button.setAttribute('aria-label','Digital Consultations inbox');
      button.title='Digital Consultations';
      button.innerHTML=`<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 5h16v11H15l-3 3-3-3H4V5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M8 9h8M8 12h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><span class="ec-inbox-badge">0</span>`;
      if(actions) actions.insertAdjacentElement('beforebegin',button); else topbar.appendChild(button);
    });
    fetch('/api/consultations/unread-count',{cache:'no-store',credentials:'same-origin'})
      .then(r=>r.ok?r.json():null)
      .then(data=>{
        const count=Number(data?.count||0);
        document.querySelectorAll('.ec-inbox-button').forEach(button=>{
          const badge=button.querySelector('.ec-inbox-badge');
          if(count>0){button.classList.add('has-unread');badge.textContent=count>99?'99+':String(count);}else{button.classList.remove('has-unread');badge.textContent='0';}
        });
      }).catch(()=>{});
  };

  const addMobileDrawer=()=>{
    const sidebar=document.querySelector('.sidebar');
    if(!sidebar||document.querySelector('.ec-mobile-menu-toggle')) return;
    const toggle=document.createElement('button');
    toggle.type='button';
    toggle.className='ec-mobile-menu-toggle';
    toggle.setAttribute('aria-label','Open navigation');
    toggle.setAttribute('aria-controls','empty-chair-sidebar');
    toggle.setAttribute('aria-expanded','false');
    toggle.innerHTML='<span></span>';
    sidebar.id=sidebar.id||'empty-chair-sidebar';
    const backdrop=document.createElement('button');
    backdrop.type='button';
    backdrop.className='ec-mobile-nav-backdrop';
    backdrop.setAttribute('aria-label','Close navigation');
    document.body.appendChild(backdrop);
    document.body.appendChild(toggle);
    const setOpen=open=>{
      document.body.classList.toggle('ec-nav-open',open);
      toggle.setAttribute('aria-expanded',open?'true':'false');
      toggle.setAttribute('aria-label',open?'Close navigation':'Open navigation');
    };
    toggle.addEventListener('click',()=>setOpen(!document.body.classList.contains('ec-nav-open')));
    backdrop.addEventListener('click',()=>setOpen(false));
    sidebar.addEventListener('click',event=>{
      const link=event.target.closest('a[href]');
      if(link&&matchMedia('(max-width:1024px)').matches) setOpen(false);
    });
    document.addEventListener('keydown',event=>{if(event.key==='Escape')setOpen(false)});
    matchMedia('(min-width:1025px)').addEventListener?.('change',event=>{if(event.matches)setOpen(false)});
  };

  const addContestNav=()=>{
    const desktopAnchor=document.querySelector('a[href="/concierge-leads"]');
    if(desktopAnchor && !document.querySelector('.contest-nav-link')){
      const link=desktopAnchor.cloneNode(true);
      link.classList.add('contest-nav-link');
      link.classList.remove('active');
      link.href='/contest';
      const label=link.querySelector('span:last-child');
      if(label) label.textContent='Contest';
      desktopAnchor.insertAdjacentElement('afterend',link);
    }
    const moreSheet=document.querySelector('.mobile-more-sheet');
    if(moreSheet && !moreSheet.querySelector('a[href="/contest"]')){
      const source=moreSheet.querySelector('a[href="/concierge-leads"]');
      if(source){
        const link=source.cloneNode(true);
        link.href='/contest';
        const label=link.querySelector('strong');
        if(label) label.textContent='Contest';
        source.insertAdjacentElement('afterend',link);
      }
    }
  };
  const boot=()=>{fixDashboardActions();addConsultationsInbox();addContestNav();addMobileDrawer();};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();

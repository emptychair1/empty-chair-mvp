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
      css.href='/static/dashboard-top-actions.css?v=2';
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
  const boot=()=>{fixDashboardActions();addContestNav();};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot,{once:true}); else boot();
})();

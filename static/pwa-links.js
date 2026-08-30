(()=>{
  const ensureLink=(rel,href,attrs={})=>{
    let link=document.head.querySelector(`link[rel="${rel}"]`);
    if(!link){link=document.createElement('link');link.rel=rel;document.head.appendChild(link);}
    link.href=href;
    Object.entries(attrs).forEach(([k,v])=>link.setAttribute(k,v));
  };
  ensureLink('manifest','/manifest.webmanifest?v=2');
  ensureLink('icon','/static/favicon.png?v=2',{type:'image/png',sizes:'32x32'});
  ensureLink('apple-touch-icon','/static/app-icon.png?v=2');
  let theme=document.head.querySelector('meta[name="theme-color"]');
  if(!theme){theme=document.createElement('meta');theme.name='theme-color';document.head.appendChild(theme);}
  theme.content='#b1ff00';
  if('serviceWorker' in navigator){window.addEventListener('load',()=>{navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(()=>{});},{once:true});}

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
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',addContestNav,{once:true}); else addContestNav();
})();

(()=>{
  const ensureLink=(rel,href,attrs={})=>{
    let link=document.head.querySelector(`link[rel="${rel}"]`);
    if(!link){link=document.createElement('link');link.rel=rel;document.head.appendChild(link);}
    link.href=href;
    Object.entries(attrs).forEach(([k,v])=>link.setAttribute(k,v));
  };
  ensureLink('manifest','/manifest.webmanifest');
  ensureLink('icon','/static/app-icon.png?v=1',{type:'image/png'});
  ensureLink('apple-touch-icon','/static/app-icon.png?v=1');
  let theme=document.head.querySelector('meta[name="theme-color"]');
  if(!theme){theme=document.createElement('meta');theme.name='theme-color';document.head.appendChild(theme);}
  theme.content='#b1ff00';
})();

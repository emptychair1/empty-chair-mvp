(function () {
  function ensureLink(rel, href, extra) {
    var link = document.querySelector('link[rel="' + rel + '"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = rel;
      document.head.appendChild(link);
    }
    link.href = href;
    if (extra) Object.keys(extra).forEach(function (key) { link.setAttribute(key, extra[key]); });
  }

  function ensureMeta(name, content) {
    var meta = document.querySelector('meta[name="' + name + '"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = name;
      document.head.appendChild(meta);
    }
    meta.content = content;
  }

  ensureLink('manifest', '/manifest.webmanifest?v=3');
  ensureLink('icon', '/static/favicon.png?v=3', { type: 'image/png', sizes: '32x32' });
  ensureLink('apple-touch-icon', '/static/apple-touch-icon.png?v=3', { sizes: '180x180' });
  ensureMeta('theme-color', '#b1ff00');
  ensureMeta('apple-mobile-web-app-capable', 'yes');
  ensureMeta('apple-mobile-web-app-status-bar-style', 'black-translucent');
  ensureMeta('apple-mobile-web-app-title', 'Empty Chair');
  ensureMeta('mobile-web-app-capable', 'yes');

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
    });
  }

  var isIOS = /iphone|ipad|ipod/i.test(window.navigator.userAgent);
  var isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;

  if (isIOS && !isStandalone && !sessionStorage.getItem('emptyChairPwaHintDismissed')) {
    window.addEventListener('load', function () {
      setTimeout(function () {
        var hint = document.createElement('div');
        hint.className = 'pwa-install-hint';
        hint.innerHTML = '<div><strong>Install Empty Chair</strong><span>Tap Share, then “Add to Home Screen” for the full-screen app experience.</span></div><button type="button" aria-label="Dismiss install tip">×</button>';
        document.body.appendChild(hint);
        hint.querySelector('button').addEventListener('click', function () {
          sessionStorage.setItem('emptyChairPwaHintDismissed', '1');
          hint.remove();
        });
      }, 1200);
    });
  }
})();

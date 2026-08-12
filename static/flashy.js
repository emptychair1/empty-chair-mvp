(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const glow = document.createElement('div');
  glow.className = 'flash-cursor-glow';
  document.body.appendChild(glow);

  if (!reduceMotion) {
    window.addEventListener('pointermove', (event) => {
      glow.style.left = event.clientX + 'px';
      glow.style.top = event.clientY + 'px';
    }, { passive: true });
  }

  const tiltTargets = document.querySelectorAll('.war-hero, .live-card, .activity-card, .metric-card');
  tiltTargets.forEach((card) => {
    card.classList.add('flash-tilt');
    if (reduceMotion) return;
    card.addEventListener('pointermove', (event) => {
      const rect = card.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width;
      const py = (event.clientY - rect.top) / rect.height;
      const rotateY = (px - 0.5) * 3.5;
      const rotateX = (0.5 - py) * 3.5;
      card.style.transform = `perspective(900px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-2px)`;
    });
    card.addEventListener('pointerleave', () => {
      card.style.transform = '';
    });
  });

  const toastStack = document.createElement('div');
  toastStack.className = 'flash-toast-stack';
  document.body.appendChild(toastStack);

  function toast(title, copy, tone = '') {
    const node = document.createElement('div');
    node.className = `flash-toast ${tone}`.trim();
    node.innerHTML = `<div class="flash-toast-title">${title}</div><div class="flash-toast-copy">${copy}</div>`;
    toastStack.appendChild(node);
    window.setTimeout(() => {
      node.classList.add('out');
      window.setTimeout(() => node.remove(), 320);
    }, 4200);
  }

  function celebrate() {
    if (reduceMotion) return;
    const palette = ['#e12626', '#d0aa70', '#75cb45', '#f1e6d2'];
    for (let i = 0; i < 28; i += 1) {
      const bit = document.createElement('span');
      bit.className = 'flash-confetti';
      bit.style.left = `${50 + (Math.random() - 0.5) * 18}vw`;
      bit.style.top = '18vh';
      bit.style.background = palette[i % palette.length];
      bit.style.setProperty('--x', `${(Math.random() - 0.5) * 420}px`);
      bit.style.setProperty('--y', `${260 + Math.random() * 260}px`);
      bit.style.setProperty('--r', `${Math.random() * 900 - 450}deg`);
      document.body.appendChild(bit);
      window.setTimeout(() => bit.remove(), 1500);
    }
  }

  const recovered = document.getElementById('recoveredTicker');
  if (recovered) {
    window.setTimeout(() => recovered.classList.add('flash-revenue-pop'), 850);
  }

  const activeStatus = document.querySelector('.status.RECOVERY_ACTIVE');
  const bookedStatus = document.querySelector('.status.BOOKED, .status.COMPLETED, .status.CLAIMED, .status.CONFIRMED');

  if (activeStatus) {
    window.setTimeout(() => toast('Recovery Active', 'A chair is moving through the recovery queue now.', 'hot'), 900);
  } else if (bookedStatus) {
    window.setTimeout(() => {
      toast('Chair Recovered', 'Recovered revenue is locked in.', 'good');
      celebrate();
    }, 900);
  }

  document.querySelectorAll('.opening-row').forEach((row) => {
    const status = row.querySelector('.status');
    if (!status) return;
    row.addEventListener('mouseenter', () => {
      if (status.classList.contains('RECOVERY_ACTIVE')) row.classList.add('flash-edge-pulse');
    });
    row.addEventListener('animationend', () => row.classList.remove('flash-edge-pulse'));
  });

  document.addEventListener('click', (event) => {
    const button = event.target.closest('.button');
    if (!button || reduceMotion) return;
    button.animate([
      { transform: 'scale(1)' },
      { transform: 'scale(.97)' },
      { transform: 'scale(1)' }
    ], { duration: 180, easing: 'ease-out' });
  });
})();

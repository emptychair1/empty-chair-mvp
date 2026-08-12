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

  function buildRevenuePulseChart() {
    const warRoom = document.querySelector('.war-room');
    const rows = [...document.querySelectorAll('#openings .opening-row')];
    if (!warRoom || !rows.length) return;

    const months = {
      JAN: '01', FEB: '02', MAR: '03', APR: '04', MAY: '05', JUN: '06',
      JUL: '07', AUG: '08', SEP: '09', OCT: '10', NOV: '11', DEC: '12'
    };
    const recoveredStatuses = new Set(['CLAIMED', 'BOOKED', 'COMPLETED', 'CONFIRMED']);
    const riskStatuses = new Set(['OPEN', 'RECOVERY_ACTIVE']);
    const daily = new Map();

    rows.forEach((row) => {
      const statusNode = row.querySelector('.status');
      const monthNode = row.querySelector('.date-month');
      const dayNode = row.querySelector('.date-day');
      const yearNode = row.querySelector('.date-dow');
      const metaNode = row.querySelector('.opening-meta');
      if (!statusNode || !monthNode || !dayNode || !yearNode || !metaNode) return;

      const month = months[monthNode.textContent.trim().toUpperCase()];
      const day = dayNode.textContent.trim().padStart(2, '0');
      const year = yearNode.textContent.trim();
      if (!month || !/^\d{4}$/.test(year) || !/^\d{2}$/.test(day)) return;

      const priceMatch = metaNode.textContent.match(/\$([\d,]+(?:\.\d+)?)/);
      const price = priceMatch ? Number(priceMatch[1].replace(/,/g, '')) : 0;
      const status = statusNode.textContent.trim().toUpperCase();
      const key = `${year}-${month}-${day}`;
      const current = daily.get(key) || { recovered: 0, risk: 0 };

      if (recoveredStatuses.has(status)) current.recovered += price;
      if (riskStatuses.has(status)) current.risk += price;
      daily.set(key, current);
    });

    const keys = [...daily.keys()].sort();
    if (!keys.length) return;

    let cumulativeRecovered = 0;
    const data = keys.map((key) => {
      const values = daily.get(key);
      cumulativeRecovered += values.recovered;
      return {
        date: key,
        label: new Date(`${key}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
        recovered: cumulativeRecovered,
        risk: values.risk
      };
    });

    const totalRecovered = data[data.length - 1].recovered;
    const currentRisk = data.reduce((sum, point) => sum + point.risk, 0);
    const maxValue = Math.max(1, ...data.flatMap((point) => [point.recovered, point.risk]));

    const width = 1000;
    const height = 360;
    const left = 58;
    const right = 26;
    const top = 28;
    const bottom = 52;
    const chartW = width - left - right;
    const chartH = height - top - bottom;
    const x = (index) => data.length === 1 ? left + chartW / 2 : left + (index / (data.length - 1)) * chartW;
    const y = (value) => top + chartH - (value / maxValue) * chartH;
    const points = (field) => data.map((point, index) => `${x(index)},${y(point[field])}`).join(' ');
    const areaPoints = `${left},${top + chartH} ${points('recovered')} ${x(data.length - 1)},${top + chartH}`;

    const grid = [0, .25, .5, .75, 1].map((ratio) => {
      const gy = top + chartH * ratio;
      const value = Math.round(maxValue * (1 - ratio));
      return `<line x1="${left}" y1="${gy}" x2="${width - right}" y2="${gy}" class="revenue-chart-grid" />
        <text x="${left - 12}" y="${gy + 4}" text-anchor="end" class="revenue-chart-axis">$${value.toLocaleString()}</text>`;
    }).join('');

    const labelIndexes = data.length <= 6
      ? data.map((_, index) => index)
      : [0, Math.floor((data.length - 1) / 2), data.length - 1];
    const xLabels = labelIndexes.map((index) =>
      `<text x="${x(index)}" y="${height - 18}" text-anchor="middle" class="revenue-chart-axis">${data[index].label}</text>`
    ).join('');

    const hitTargets = data.map((point, index) => `
      <g class="revenue-chart-hit" data-index="${index}">
        <circle cx="${x(index)}" cy="${y(point.recovered)}" r="6" class="revenue-chart-dot recovered-dot" />
        <circle cx="${x(index)}" cy="${y(point.risk)}" r="5" class="revenue-chart-dot risk-dot" />
        <rect x="${Math.max(left, x(index) - Math.max(18, chartW / Math.max(2, data.length) / 2))}" y="${top}" width="${Math.max(36, chartW / Math.max(1, data.length))}" height="${chartH}" fill="transparent" />
      </g>`).join('');

    const section = document.createElement('section');
    section.className = 'revenue-pulse-card';
    section.innerHTML = `
      <div class="revenue-pulse-head">
        <div>
          <div class="section-cap">Revenue Recovery Pulse</div>
          <h2>Recovered vs. Exposed</h2>
          <p>Cumulative revenue locked back in compared with open revenue still at risk.</p>
        </div>
        <div class="revenue-pulse-kpis">
          <div><span>Recovered</span><strong class="good">$${Math.round(totalRecovered).toLocaleString()}</strong></div>
          <div><span>Exposure</span><strong class="hot">$${Math.round(currentRisk).toLocaleString()}</strong></div>
        </div>
      </div>
      <div class="revenue-chart-wrap">
        <svg class="revenue-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Recovered revenue and revenue at risk chart">
          <defs>
            <linearGradient id="recoveredArea" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#75cb45" stop-opacity=".26" />
              <stop offset="100%" stop-color="#75cb45" stop-opacity="0" />
            </linearGradient>
            <filter id="greenGlow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
            <filter id="redGlow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          ${grid}
          ${xLabels}
          <polygon points="${areaPoints}" fill="url(#recoveredArea)" class="revenue-chart-area" />
          <polyline points="${points('recovered')}" class="revenue-chart-line recovered-line" filter="url(#greenGlow)" />
          <polyline points="${points('risk')}" class="revenue-chart-line risk-line" filter="url(#redGlow)" />
          ${hitTargets}
        </svg>
        <div class="revenue-chart-tooltip" hidden></div>
      </div>
      <div class="revenue-chart-legend">
        <span><i class="legend-line recovered"></i> Recovered revenue</span>
        <span><i class="legend-line risk"></i> Revenue at risk</span>
      </div>`;

    warRoom.insertAdjacentElement('afterend', section);

    const tooltip = section.querySelector('.revenue-chart-tooltip');
    const svg = section.querySelector('.revenue-chart');
    section.querySelectorAll('.revenue-chart-hit').forEach((hit) => {
      hit.addEventListener('pointerenter', () => {
        const point = data[Number(hit.dataset.index)];
        tooltip.hidden = false;
        tooltip.innerHTML = `<b>${point.label}</b><span>Recovered <strong>$${Math.round(point.recovered).toLocaleString()}</strong></span><span>At risk <strong>$${Math.round(point.risk).toLocaleString()}</strong></span>`;
      });
      hit.addEventListener('pointermove', (event) => {
        const rect = section.querySelector('.revenue-chart-wrap').getBoundingClientRect();
        tooltip.style.left = `${Math.min(rect.width - 170, Math.max(8, event.clientX - rect.left + 14))}px`;
        tooltip.style.top = `${Math.max(8, event.clientY - rect.top - 72)}px`;
      });
      hit.addEventListener('pointerleave', () => {
        tooltip.hidden = true;
      });
    });

    if (!reduceMotion && svg) {
      window.requestAnimationFrame(() => section.classList.add('chart-live'));
    } else {
      section.classList.add('chart-live');
    }
  }

  buildRevenuePulseChart();

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

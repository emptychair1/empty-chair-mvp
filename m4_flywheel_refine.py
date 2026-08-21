"""Presentation refinement for the Concierge × M4 cinematic flywheel demo."""
import m4_flywheel_demo as demo


_HEAD = r'''
<style>
/* Humanize the demo and give each beat enough time to read. */
.bubble,.profile,.cand,.decision,.phone,.book,.signal{transition-duration:1.05s!important}
.human-layer{position:absolute;inset:20px;z-index:6;display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:18px;pointer-events:none}
.people-chat{align-self:start;max-width:760px;margin:20px auto;width:100%;padding-top:6px}.person-line{display:grid;grid-template-columns:46px 1fr;gap:11px;align-items:end;margin:17px 0;opacity:.14;transform:translateY(16px);transition:opacity .9s,transform .9s}.person-line.customer{grid-template-columns:1fr 46px}.person-line.show{opacity:1;transform:none}.face{width:44px;height:44px;border-radius:50%;border:1px solid #4b594a;display:grid;place-items:center;font:900 11px ui-monospace,monospace;background:radial-gradient(circle at 34% 28%,#b9b59f,#62695a 42%,#1c231c 75%);box-shadow:0 10px 28px rgba(0,0,0,.35)}.face.m4face{background:radial-gradient(circle at 35% 28%,rgba(235,255,212,.9),rgba(183,255,60,.45) 28%,rgba(183,255,60,.08) 68%);color:#eaffcf;box-shadow:0 0 28px rgba(183,255,60,.3)}.person-line.customer .face{grid-column:2}.speech{border:1px solid #313b31;background:#101510;padding:13px 15px;line-height:1.5;font-size:13px;box-shadow:0 14px 38px rgba(0,0,0,.18)}.customer .speech{background:#171a16;border-color:#444a42}.who{display:block;font:800 9px ui-monospace,monospace;letter-spacing:.11em;color:var(--g);margin-bottom:5px}.customer .who{color:#b9b9b2}
.trait-rail{align-self:center;border:1px solid #344034;background:rgba(8,12,8,.94);padding:16px;backdrop-filter:blur(8px);box-shadow:0 30px 80px rgba(0,0,0,.35)}.trait-rail h3{font-size:13px;margin:0 0 4px}.trait-rail p{font-size:10px;color:var(--m);line-height:1.5;margin:0 0 12px}.trait{border:1px solid #303a30;padding:9px 10px;margin:7px 0;opacity:.18;transform:translateX(12px);transition:.75s;background:#0d120d}.trait.show{opacity:1;transform:none;border-color:var(--g);box-shadow:inset 3px 0 0 var(--g)}.trait b{display:block;font-size:10px;color:#e8eee3}.trait span{display:block;color:#98a294;font:700 9px ui-monospace,monospace;margin-top:3px}.trait.show span{color:#cce9b8}.trait .check{float:right;color:var(--g);opacity:0}.trait.show .check{opacity:1}.human-note{margin-top:10px;color:#9ba596;font:700 9px/1.55 ui-monospace,monospace;border-top:1px solid #293329;padding-top:10px}.stage:first-of-type .scene{min-height:680px}.scene.humanized>.chat{opacity:.04;filter:blur(1px)}
@media(max-width:900px){.human-layer{grid-template-columns:1fr;position:relative;inset:auto}.trait-rail{margin-top:10px}.stage:first-of-type .scene{min-height:930px}}
</style>
<script>
(()=>{const nativeSetTimeout=window.setTimeout.bind(window);window.setTimeout=(fn,ms,...args)=>nativeSetTimeout(fn,Math.round((Number(ms)||0)*1.65),...args);window.__EMPTY_CHAIR_CINEMATIC_SPEED__=.61;})();
</script>
'''

_BODY = r'''
<script>
(()=>{
 const boot=()=>{
  const first=document.querySelector('.stage .scene'); if(!first||first.dataset.humanized)return; first.dataset.humanized='1'; first.classList.add('humanized');
  const layer=document.createElement('div'); layer.className='human-layer'; layer.innerHTML=`
   <div class="people-chat">
    <div class="person-line" data-beat="0"><div class="face m4face">C</div><div class="speech"><span class="who">CONCIERGE</span>What are you actually hoping to get tattooed—not just the style, but the idea?</div></div>
    <div class="person-line customer" data-beat="1"><div class="speech"><span class="who">MAYA</span>A botanical shoulder piece. Black and grey, bold enough to age well, but not delicate-fine-line.</div><div class="face">MC</div></div>
    <div class="person-line" data-beat="2"><div class="face m4face">C</div><div class="speech"><span class="who">CONCIERGE</span>That narrows the artist fit a lot. Would you take a short-notice opening if the right artist had one?</div></div>
    <div class="person-line customer" data-beat="3"><div class="speech"><span class="who">MAYA</span>Absolutely. A day of notice is fine. Budget is around $450–$700 and I can drive about 35 miles.</div><div class="face">MC</div></div>
    <div class="person-line" data-beat="4"><div class="face m4face">C</div><div class="speech"><span class="who">CONCIERGE</span>Perfect. I’m turning that into a customer profile you keep—and M4 can use those preferences when a real gap appears.</div></div>
   </div>
   <aside class="trait-rail"><h3>Signals Concierge just learned</h3><p>Characteristics are extracted from what Maya actually says.</p>
    <div class="trait" data-trait="1"><span class="check">✓</span><b>STYLE</b><span>black & grey · botanical · illustrative</span></div>
    <div class="trait" data-trait="2"><span class="check">✓</span><b>PLACEMENT</b><span>shoulder / upper arm</span></div>
    <div class="trait" data-trait="3"><span class="check">✓</span><b>SHORT-NOTICE FLEXIBILITY</b><span>yes · 24 hours</span></div>
    <div class="trait" data-trait="4"><span class="check">✓</span><b>BUDGET</b><span>$450–$700</span></div>
    <div class="trait" data-trait="5"><span class="check">✓</span><b>TRAVEL</b><span>up to 35 miles</span></div>
    <div class="trait" data-trait="6"><span class="check">✓</span><b>ARTIST CHARACTERISTICS</b><span>patient · strong black & grey · illustrative</span></div>
    <div class="human-note">ZERO-PARTY DATA → explicit, volunteered, useful to the customer and the shop.</div>
   </aside>`; first.prepend(layer);
  const lines=[...layer.querySelectorAll('.person-line')],traits=[...layer.querySelectorAll('.trait')];
  const wait=ms=>new Promise(r=>setTimeout(r,ms));
  async function humanSequence(){for(let i=0;i<lines.length;i++){lines[i].classList.add('show'); if(i===1){traits[0].classList.add('show');traits[1].classList.add('show')} if(i===3){traits.slice(2,5).forEach(x=>x.classList.add('show'))} if(i===4){traits[5].classList.add('show')} await wait(1250)}}
  const start=document.getElementById('start'); if(start)start.addEventListener('click',()=>{lines.forEach(x=>x.classList.remove('show'));traits.forEach(x=>x.classList.remove('show'));setTimeout(humanSequence,700)},{capture:true});
  const replay=document.getElementById('replay'); if(replay)replay.addEventListener('click',()=>{lines.forEach(x=>x.classList.remove('show'));traits.forEach(x=>x.classList.remove('show'))});
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
</script>
'''


def refine(html: str) -> str:
    if 'human-layer' in html:
        return html
    html = html.replace('</head>', _HEAD + '</head>')
    html = html.replace('</body>', _BODY + '</body>')
    return html


demo._HTML = refine(demo._HTML)

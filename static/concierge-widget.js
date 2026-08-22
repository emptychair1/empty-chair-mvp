(()=>{
const cfg=window.EMPTY_CHAIR_CONCIERGE||{};
const sessionId='conc_'+crypto.getRandomValues(new Uint32Array(3)).join('');
const state={shop_id:cfg.shopId||'shop_live_demo',session_id:sessionId,project:'',styles:'',placement:'',budget:'',timing:'',short_notice:'',artist_vibe:'',travel:'',location:'',name:'',phone:'',email:'',contact_preference:'',offer_consent:'',step:0};
const thread=document.getElementById('thread'),input=document.getElementById('answer'),send=document.getElementById('send'),quick=document.getElementById('quick');
const questions=[
{key:'project',ask:"Tell me a little more about the idea. Rough is totally fine.",placeholder:'Describe your tattoo idea…'},
{key:'styles',ask:'Is there a style you already have in mind?',placeholder:'Black & grey, fine line, traditional…',options:['Black & grey','Fine line','Traditional','Blackwork','Realism','Not sure yet']},
{key:'placement',ask:'Where are you thinking about putting it?',placeholder:'Forearm, thigh, ribs…'},
{key:'budget',ask:'Do you have a rough budget in mind?',placeholder:'Choose or type a range…',options:['$150–300','$300–600','$600–1,000','$1,000+','Flexible']},
{key:'timing',ask:'And what does timing look like for you?',placeholder:'Choose or describe…',options:['Ready now','This month','Next few months','Still figuring it out']},
{key:'artist_vibe',ask:'Any artist here you like already, or anything you want in the artist?',placeholder:'Artist name, style, vibe…'},
{key:'name',ask:"Got it. What's your name?",placeholder:'Your name'},
{key:'phone',ask:"What's the best mobile number for the shop to reach you?",placeholder:'Mobile number'},
{key:'email',ask:"And an email, if you'd like to add one. You can type skip.",placeholder:'Email or skip'},
{key:'contact_preference',ask:'How would you rather hear back?',placeholder:'Choose one…',options:['Text','Email','Either']},
{key:'offer_consent',ask:'Is it okay for the shop to contact you about this tattoo and relevant openings?',placeholder:'Choose one…',options:['Yes','No']}
];
function bubble(text,who='concierge',small=''){const d=document.createElement('div');d.className='message '+who;d.textContent=text;if(small){const s=document.createElement('small');s.textContent=small;d.appendChild(s)}thread.appendChild(d);thread.scrollTop=thread.scrollHeight;return d}
function typing(){const d=document.createElement('div');d.className='message concierge';d.innerHTML='<span class="typing"><i></i><i></i><i></i></span>';thread.appendChild(d);thread.scrollTop=thread.scrollHeight;return d}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function setQuick(q){quick.innerHTML='';(q.options||[]).forEach(opt=>{const b=document.createElement('button');b.type='button';b.textContent=opt;b.onclick=()=>answer(opt);quick.appendChild(b)})}
async function ask(){const q=questions[state.step];if(!q)return finish();input.placeholder=q.placeholder||'Type a message…';input.disabled=false;send.disabled=false;setQuick(q);const t=typing();await sleep(180);t.remove();bubble(q.ask,'concierge');input.focus()}
async function answer(raw){if(send.disabled)return;const q=questions[state.step];if(!q)return;let v=String(raw||'').trim();if(!v)return;if(q.key==='email'&&v.toLowerCase()==='skip')v='';if(q.key==='offer_consent')v=v.toLowerCase().startsWith('y')?'yes':'no';state[q.key]=v;bubble(raw,'user');input.value='';input.disabled=true;send.disabled=true;quick.innerHTML='';state.step++;await sleep(120);await ask()}
async function finish(){input.disabled=true;send.disabled=true;quick.innerHTML='';const t=typing();await sleep(220);t.remove();bubble("Perfect. I'll send this to the shop so they know what you're looking for.",'concierge');const fd=new FormData();['shop_id','session_id','project','styles','placement','budget','timing','short_notice','artist_vibe','travel','location','name','phone','email','contact_preference'].forEach(k=>fd.append(k,state[k]||''));fd.append('offer_consent',state.offer_consent||'no');try{const r=await fetch('/api/concierge/profile',{method:'POST',body:fd,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'Could not send your details');bubble('Done — the shop has your details.','concierge');input.placeholder='Sent to the shop'}catch(e){bubble('I had trouble sending that. Tap Retry and I’ll try again.','concierge');send.disabled=false;send.textContent='Retry';send.onclick=()=>finish()}}
send.addEventListener('click',()=>answer(input.value));input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();answer(input.value)}});setTimeout(()=>ask(),500);
})();
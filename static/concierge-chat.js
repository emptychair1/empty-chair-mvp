(()=>{
  const cfg=window.EMPTY_CHAIR_CONCIERGE||{};
  const state={
    shop_id:cfg.shopId||'shop_live_demo',
    project:'',styles:'',placement:'',budget:'',timing:'',short_notice:'',artist_vibe:'',travel:'',
    name:'',phone:'',email:'',contact_preference:'',offer_consent:'',step:0
  };
  const thread=document.getElementById('thread'),input=document.getElementById('answer'),send=document.getElementById('send'),quick=document.getElementById('quick');
  const pct=document.getElementById('confidence'),bar=document.getElementById('confidenceBar'),gift=document.getElementById('gift'),giftBody=document.getElementById('giftBody'),giftId=document.getElementById('giftId');
  const fields={project:'Project',styles:'Style',placement:'Placement',budget:'Budget',timing:'Timing',short_notice:'Short notice',artist_vibe:'Artist fit',travel:'Travel',name:'Name',phone:'Phone',email:'Email',contact_preference:'Contact preference',offer_consent:'Offer consent'};
  const questions=[
    {key:'project',ask:"Tell me what you're actually thinking about getting. Rough idea is fine — I don't need a polished brief.",placeholder:'Describe the tattoo idea…'},
    {key:'styles',ask:'What style feels closest to it?',placeholder:'Traditional, black & gray, fine line…',options:['Traditional','Black & gray','Fine line','Blackwork','Realism','Anime','Not sure yet']},
    {key:'placement',ask:'Where are you picturing it on your body?',placeholder:'Forearm, thigh, ribs…'},
    {key:'budget',ask:'What budget would feel comfortable if the right artist and opening appeared?',placeholder:'Choose or type a range…',options:['$150–300','$300–600','$600–1,000','$1,000+','Flexible']},
    {key:'timing',ask:'How soon would you actually move on the right tattoo?',placeholder:'Choose or describe…',options:['Today','This week','This month','Next 3 months','Just exploring']},
    {key:'short_notice',ask:'One useful question: if a strong match had a cancellation tomorrow, would you want to know?',placeholder:'Choose one…',options:['Yes — I can move fast','Maybe, with 2–3 days notice','No — I need to plan ahead']},
    {key:'artist_vibe',ask:'What matters most to you in the artist — specialty, personality, appointment vibe, anything?',placeholder:'Traditional specialist, collaborative, quiet…'},
    {key:'travel',ask:'How far would you go for the right artist?',placeholder:'Choose or type…',options:['15 miles','30 miles','60 miles','Worth traveling for']},
    {key:'name',ask:"I have the tattoo part. What's your name so I can make this an actual profile?",placeholder:'Your name'},
    {key:'phone',ask:'What mobile number should belong to the profile?',placeholder:'Mobile number'},
    {key:'email',ask:"Email too, if you want it attached. You can type 'skip'.",placeholder:'Email or skip'},
    {key:'contact_preference',ask:'If you do want matching openings, how would you rather hear about them?',placeholder:'Choose one…',options:['Text','Email','Either']},
    {key:'offer_consent',ask:'Last thing, and this one is deliberately explicit: may Empty Chair contact you about tattoo openings that match this profile?',placeholder:'Choose Yes or No',options:['Yes — send relevant openings','No — profile only']}
  ];
  function bubble(text,who='concierge',small=''){
    const d=document.createElement('div');d.className='message '+who;d.innerHTML=text+(small?`<small>${small}</small>`:'');thread.appendChild(d);thread.scrollTop=thread.scrollHeight;return d;
  }
  function typing(){const d=bubble('<span class="typing"><i></i><i></i><i></i></span>','concierge');return d}
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  function confidence(){
    const keys=['project','styles','placement','budget','timing','short_notice','artist_vibe','travel'];
    const known=keys.filter(k=>state[k]).length;return Math.round(25+70*known/keys.length);
  }
  function updateSignals(){
    const c=confidence();pct.textContent=c+'%';bar.style.width=c+'%';
    Object.keys(fields).forEach(k=>{const el=document.querySelector(`[data-signal="${k}"]`);if(!el)return;const b=el.querySelector('b');let v=state[k];if(k==='offer_consent')v=v==='yes'?'YES':v==='no'?'NO':'';b.textContent=v||'unknown';el.classList.toggle('learned',!!v)});
  }
  function setQuick(q){quick.innerHTML='';(q.options||[]).forEach(opt=>{const b=document.createElement('button');b.type='button';b.textContent=opt;b.onclick=()=>answer(opt);quick.appendChild(b)})}
  async function ask(){
    if(state.step>=questions.length)return finish();
    const q=questions[state.step];input.placeholder=q.placeholder||'Type your answer…';input.disabled=false;send.disabled=false;setQuick(q);
    const t=typing();await sleep(260);t.remove();bubble(q.ask,'concierge',q.key==='offer_consent'?'Your permission controls whether this profile can receive automated offers.':'Concierge // customer value');input.focus();
  }
  async function answer(raw){
    if(send.disabled)return;const q=questions[state.step];let v=String(raw||'').trim();if(!v)return;
    if(q.key==='email'&&v.toLowerCase()==='skip')v='';
    if(q.key==='offer_consent')v=v.toLowerCase().startsWith('yes')?'yes':'no';
    state[q.key]=v;bubble(raw,'user');input.value='';input.disabled=true;send.disabled=true;quick.innerHTML='';updateSignals();state.step++;
    await sleep(180);await ask();
  }
  async function finish(){
    const t=typing();await sleep(300);t.remove();bubble("That's enough. I'm creating your customer profile now, including the tattoo signals you chose to give me.",'concierge');
    const fd=new FormData();
    ['shop_id','project','styles','placement','budget','timing','short_notice','artist_vibe','travel','name','phone','email','contact_preference'].forEach(k=>fd.append(k,state[k]||''));
    fd.append('offer_consent',state.offer_consent||'no');
    try{
      const r=await fetch('/api/concierge/profile',{method:'POST',body:fd,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'Could not create customer profile');
      bubble(state.offer_consent==='yes'?"Done. Your profile is live, and matching openings are allowed to reach you.":"Done. Your profile is live. I will not use it for opening alerts unless you change that permission later.",'concierge','Profile created');
      gift.classList.add('show');giftBody.innerHTML=`<b>${j.value.name}</b><br>${j.value.style} · ${j.value.budget}<br>${j.value.short_notice}<br>Preferred contact: ${j.value.contact_preference}<br>Offer permission: ${j.communication_consent?'YES':'NO'}<br><br>M4 customer-model confidence moved from ${j.m4_confidence_before}% to ${j.m4_confidence_after}%.`;giftId.textContent='CUSTOMER PROFILE // '+j.customer_id;
      pct.textContent=j.m4_confidence_after+'%';bar.style.width=j.m4_confidence_after+'%';
      input.placeholder='Profile complete';input.disabled=true;send.disabled=true;
    }catch(e){bubble('I hit a save error. Your answers are still on this screen, so nothing is lost. '+e.message,'concierge');input.disabled=false;send.disabled=false;send.textContent='Retry';send.onclick=()=>finish();}
  }
  send.addEventListener('click',()=>answer(input.value));input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();answer(input.value)}});
  updateSignals();
  setTimeout(()=>ask(),250);
})();

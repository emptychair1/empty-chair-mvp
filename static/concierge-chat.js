(()=>{
  const cfg=window.EMPTY_CHAIR_CONCIERGE||{};
  const sessionId='conc_'+crypto.getRandomValues(new Uint32Array(3)).join('');
  const state={
    shop_id:cfg.shopId||'shop_live_demo',session_id:sessionId,
    project:'',styles:'',placement:'',budget:'',timing:'',short_notice:'',artist_vibe:'',travel:'',location:'',
    name:'',phone:'',email:'',contact_preference:'',offer_consent:'',step:0,
    vision:false,visionSummary:'',visionTokens:[]
  };
  const thread=document.getElementById('thread'),input=document.getElementById('answer'),send=document.getElementById('send'),quick=document.getElementById('quick');
  const pct=document.getElementById('confidence'),bar=document.getElementById('confidenceBar'),gift=document.getElementById('gift'),giftBody=document.getElementById('giftBody'),giftId=document.getElementById('giftId');
  const inspirationInput=document.getElementById('inspirationInput'),analyzeImages=document.getElementById('analyzeImages'),visionStatus=document.getElementById('visionStatus'),visionChips=document.getElementById('visionChips');
  const fields={project:'Project',styles:'Style',placement:'Placement',budget:'Budget',timing:'Timing',short_notice:'Short notice',artist_vibe:'Artist fit',travel:'Travel',location:'Location',name:'Name',phone:'Phone',email:'Email',contact_preference:'Contact preference',offer_consent:'Offer consent'};
  const questions=[
    {key:'project',ask:"Tell me what you're actually thinking about getting. Rough idea is fine — I don't need a polished brief.",placeholder:'Describe the tattoo idea…',visualSkip:true},
    {key:'styles',ask:'What style feels closest to it?',placeholder:'Traditional, black & gray, fine line…',options:['Traditional','Black & gray','Fine line','Blackwork','Realism','Anime','Not sure yet'],visualSkip:true},
    {key:'placement',ask:'Where do you want it on your body?',placeholder:'Forearm, thigh, ribs…'},
    {key:'budget',ask:'What budget would feel comfortable if the right artist and opening appeared?',placeholder:'Choose or type a range…',options:['$150–300','$300–600','$600–1,000','$1,000+','Flexible']},
    {key:'timing',ask:'How soon would you actually move on the right tattoo?',placeholder:'Choose or describe…',options:['Today','This week','This month','Next 3 months','Just exploring']},
    {key:'short_notice',ask:'If a strong match had a cancellation tomorrow, would you want to know?',placeholder:'Choose one…',options:['Yes — I can move fast','Maybe, with 2–3 days notice','No — I need to plan ahead']},
    {key:'artist_vibe',ask:'Anything important about the artist or appointment vibe?',placeholder:'Collaborative, quiet, specialist…'},
    {key:'travel',ask:'How far would you go for the right artist?',placeholder:'Choose or type…',options:['15 miles','30 miles','60 miles','Worth traveling for']},
    {key:'location',ask:'What city or ZIP are you usually coming from? This is only for travel-time matching.',placeholder:'City, state or ZIP'},
    {key:'name',ask:"What's your name so I can make this an actual profile?",placeholder:'Your name'},
    {key:'phone',ask:'What mobile number should belong to the profile?',placeholder:'Mobile number'},
    {key:'email',ask:"Email too, if you want it attached. You can type 'skip'.",placeholder:'Email or skip'},
    {key:'contact_preference',ask:'If you do want matching openings, how would you rather hear about them?',placeholder:'Choose one…',options:['Text','Email','Either']},
    {key:'offer_consent',ask:'May Empty Chair contact you about tattoo openings that match this profile?',placeholder:'Choose Yes or No',options:['Yes — send relevant openings','No — profile only']}
  ];
  function bubble(text,who='concierge',small=''){
    const d=document.createElement('div');d.className='message '+who;d.innerHTML=text+(small?`<small>${small}</small>`:'');thread.appendChild(d);thread.scrollTop=thread.scrollHeight;return d;
  }
  function typing(){const d=bubble('<span class="typing"><i></i><i></i><i></i></span>','concierge');return d}
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  function confidence(){
    const keys=['project','styles','placement','budget','timing','short_notice','artist_vibe','travel','location'];
    const known=keys.filter(k=>state[k]).length;return Math.min(97,Math.round(25+70*known/keys.length+(state.vision?8:0)));
  }
  function updateSignals(){
    const c=confidence();pct.textContent=c+'%';bar.style.width=c+'%';
    Object.keys(fields).forEach(k=>{const el=document.querySelector(`[data-signal="${k}"]`);if(!el)return;const b=el.querySelector('b');let v=state[k];if(k==='offer_consent')v=v==='yes'?'YES':v==='no'?'NO':'';b.textContent=v||'unknown';el.classList.toggle('learned',!!v)});
  }
  function setQuick(q){quick.innerHTML='';(q.options||[]).forEach(opt=>{const b=document.createElement('button');b.type='button';b.textContent=opt;b.onclick=()=>answer(opt);quick.appendChild(b)})}
  function nextQuestion(){
    while(state.step<questions.length){const q=questions[state.step];if(q.visualSkip&&state.vision&&state[q.key]){state.step++;continue}return q}return null;
  }
  async function ask(){
    const q=nextQuestion();if(!q)return finish();
    input.placeholder=q.placeholder||'Type your answer…';input.disabled=false;send.disabled=false;setQuick(q);
    const t=typing();await sleep(220);t.remove();bubble(q.ask,'concierge',q.key==='offer_consent'?'Your permission controls whether this profile can receive automated offers.':q.key==='location'?'Used for geocoding and drive-time only; area statistics are never treated as facts about you.':'Concierge // only what the images cannot tell me');input.focus();
  }
  async function answer(raw){
    if(send.disabled)return;const q=nextQuestion();if(!q)return finish();let v=String(raw||'').trim();if(!v)return;
    if(q.key==='email'&&v.toLowerCase()==='skip')v='';
    if(q.key==='offer_consent')v=v.toLowerCase().startsWith('yes')?'yes':'no';
    state[q.key]=v;bubble(raw,'user');input.value='';input.disabled=true;send.disabled=true;quick.innerHTML='';updateSignals();state.step++;
    await sleep(150);await ask();
  }
  function renderVision(analysis){
    const styles=(analysis.styles||[]).slice(0,4),motifs=(analysis.motifs||[]).slice(0,3),bits=[...styles,...motifs];
    visionChips.innerHTML='';bits.forEach(x=>{const s=document.createElement('span');s.className='vision-chip';s.textContent=x;visionChips.appendChild(s)});
    if(styles.length)state.styles=styles.join(', ');
    if(analysis.summary){state.project=analysis.summary;state.visionSummary=analysis.summary}
    state.vision=true;updateSignals();
  }
  async function analyzeSelectedImages(){
    const files=[...(inspirationInput.files||[])].slice(0,6);if(!files.length){visionStatus.textContent='Choose at least one tattoo image first.';return}
    analyzeImages.disabled=true;visionStatus.classList.remove('learned');visionStatus.textContent=`Reading ${files.length} inspiration image${files.length>1?'s':''}…`;
    const merged={styles:[],motifs:[],palette:[],summary:''};let completed=0;
    for(const file of files){
      const fd=new FormData();fd.append('shop_id',state.shop_id);fd.append('session_id',state.session_id);fd.append('image',file);
      try{
        const r=await fetch('/api/concierge/inspiration',{method:'POST',body:fd,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.detail||'Image analysis failed');
        state.visionTokens.push(j.attach_token);const a=j.analysis||{};merged.styles.push(...(a.styles||[]));merged.motifs.push(...(a.motifs||[]));merged.palette.push(...(a.palette||[]));if(!merged.summary&&a.summary)merged.summary=a.summary;completed++;
      }catch(e){visionStatus.textContent='One image could not be analyzed: '+e.message}
    }
    if(completed){merged.styles=[...new Set(merged.styles)];merged.motifs=[...new Set(merged.motifs)];renderVision(merged);visionStatus.classList.add('learned');visionStatus.textContent=`Tattoo DNA started from ${completed} image${completed>1?'s':''}. I’ll only ask for the missing practical pieces.`;bubble(`I can already see the pattern${merged.styles.length?': '+merged.styles.slice(0,3).join(', '):''}. I'll use that instead of making you translate the pictures into tattoo jargon.`,'concierge','Vision → Tattoo DNA');}
    analyzeImages.disabled=false;
  }
  async function finish(){
    input.disabled=true;send.disabled=true;quick.innerHTML='';const t=typing();await sleep(260);t.remove();bubble("That's enough. I'm creating your Tattoo DNA profile now.",'concierge');
    const fd=new FormData();
    ['shop_id','session_id','project','styles','placement','budget','timing','short_notice','artist_vibe','travel','location','name','phone','email','contact_preference'].forEach(k=>fd.append(k,state[k]||''));fd.append('offer_consent',state.offer_consent||'no');
    try{
      const r=await fetch('/api/concierge/profile',{method:'POST',body:fd,cache:'no-store'}),j=await r.json();if(!r.ok)throw Error(j.error||'Could not create customer profile');
      let dna=null;
      if(state.visionTokens.length){const ar=await fetch('/api/concierge/inspiration/attach',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({shop_id:state.shop_id,session_id:state.session_id,customer_id:j.customer_id,tokens:state.visionTokens}),cache:'no-store'}),aj=await ar.json();if(ar.ok)dna=aj;}
      bubble(state.offer_consent==='yes'?"Done. Your Tattoo DNA is live, and matching openings are allowed to reach you.":"Done. Your Tattoo DNA is live. I will not use it for opening alerts unless you change that permission later.",'concierge','Profile created');
      const dnaLine=dna&&dna.tattoo_dna&&dna.tattoo_dna.styles?.length?`<br>Tattoo DNA: ${dna.tattoo_dna.styles.slice(0,4).join(' · ')}`:'';
      const drive=j.contextual_enrichment?.travel?.drive_minutes?`<br>Drive time: ~${Math.round(j.contextual_enrichment.travel.drive_minutes)} min`:'';
      gift.classList.add('show');giftBody.innerHTML=`<b>${j.value.name}</b><br>${j.value.style} · ${j.value.budget}<br>${j.value.short_notice}<br>Preferred contact: ${j.value.contact_preference}<br>Offer permission: ${j.communication_consent?'YES':'NO'}${dnaLine}${drive}`;giftId.textContent='CUSTOMER PROFILE // '+j.customer_id;
      const finalConfidence=dna?Math.max(j.m4_confidence_after,Math.round((dna.completeness||0)*100)):j.m4_confidence_after;pct.textContent=finalConfidence+'%';bar.style.width=finalConfidence+'%';input.placeholder='Profile complete';
    }catch(e){bubble('I hit a save error. Your answers are still on this screen, so nothing is lost. '+e.message,'concierge');input.disabled=false;send.disabled=false;send.textContent='Retry';send.onclick=()=>finish();}
  }
  analyzeImages.addEventListener('click',analyzeSelectedImages);send.addEventListener('click',()=>answer(input.value));input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();answer(input.value)}});
  updateSignals();setTimeout(()=>ask(),300);
})();
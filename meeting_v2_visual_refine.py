"""Meeting CSV data-gift UI: exclusive analysis playback plus retained-value download."""

# Imported here because this module is already loaded by the production Meeting bootstrap.
import meeting_v2_guardrails  # noqa: F401
import meeting_v2_data_gift  # noqa: F401

REFINE = r'''
<style id="m4-data-gift-ui-style">
#m4DataGift{position:fixed;left:50%;bottom:max(66px,calc(env(safe-area-inset-bottom) + 58px));transform:translateX(-50%);z-index:60;display:flex;align-items:center;justify-content:center;gap:9px;max-width:94vw;opacity:.94;transition:.25s ease}
#m4DataGiftLabel,#m4DataGiftDownload{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 14px;border-radius:999px;border:1px solid rgba(166,255,46,.24);background:rgba(5,9,4,.60);color:rgba(225,255,190,.96);font:700 9px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.11em;text-transform:uppercase;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 0 28px rgba(153,255,45,.08),0 10px 35px rgba(0,0,0,.28);cursor:pointer;text-decoration:none;white-space:nowrap}
#m4DataGiftLabel:before,#m4DataGiftDownload:before{content:'';width:7px;height:7px;border-radius:50%;background:#a6ff2e;box-shadow:0 0 12px rgba(166,255,46,.82)}
#m4DataGiftDownload{display:none;padding:13px 18px;border-color:rgba(166,255,46,.58);background:rgba(12,25,6,.88);color:#efffd9;box-shadow:0 0 42px rgba(153,255,45,.20),0 14px 45px rgba(0,0,0,.36);font-size:10px}
#m4DataGift.ready{bottom:max(74px,calc(env(safe-area-inset-bottom) + 66px));flex-direction:column;gap:7px}
#m4DataGift.ready #m4DataGiftDownload{display:inline-flex}
#m4DataGift.ready #m4DataGiftLabel{display:none}
#m4DataGiftInput{display:none}
#m4DataGiftStatus{max-width:min(78vw,520px);color:rgba(232,247,220,.76);font:600 9px/1.35 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.04em;text-align:center;text-shadow:0 2px 8px rgba(0,0,0,.7)}
#m4DataGift.busy #m4DataGiftLabel{pointer-events:none;opacity:.48}
@media(max-width:600px){#m4DataGift{bottom:max(62px,calc(env(safe-area-inset-bottom) + 54px));width:94vw;flex-wrap:wrap}#m4DataGift.ready{bottom:max(72px,calc(env(safe-area-inset-bottom) + 64px))}#m4DataGiftStatus{max-width:82vw;font-size:8px}#m4DataGiftDownload{padding:14px 17px;font-size:9px}}
</style>
<div id="m4DataGift" aria-label="M4 data gift upload">
  <label id="m4DataGiftLabel" for="m4DataGiftInput">Upload CSV</label>
  <input id="m4DataGiftInput" type="file" accept=".csv,text/csv">
  <a id="m4DataGiftDownload" href="#" download>Download your enriched CSV</a>
  <span id="m4DataGiftStatus">anonymized test data only</span>
</div>
<script id="m4-data-gift-ui-script">
(function(){
 const box=document.getElementById('m4DataGift'),input=document.getElementById('m4DataGiftInput'),status=document.getElementById('m4DataGiftStatus'),download=document.getElementById('m4DataGiftDownload');
 if(!box||!input||!download)return;
 let giftUrl=null,giftActive=false;

 function killCurrentM4Audio(){
   try{if(typeof sourceNode!=='undefined'&&sourceNode){sourceNode.onended=null;sourceNode.stop();sourceNode.disconnect();sourceNode=null}}catch(_){}
   try{if(typeof raf!=='undefined'&&raf)cancelAnimationFrame(raf)}catch(_){}
   try{if(typeof presence!=='undefined')presence.style.transform=''}catch(_){}
 }

 async function suspendMeetingMic(){
   giftActive=true;
   try{if(typeof busy!=='undefined')busy=true}catch(_){}
   try{
     if(typeof recorder!=='undefined'&&recorder&&recorder.state==='recording'){
       recorder.onstop=null;
       recorder.stop();
       await new Promise(r=>setTimeout(r,120));
       recorder.onstop=sendTurn;
     }
   }catch(_){}
 }

 function endMeetingListening(){
   try{if(typeof started!=='undefined')started=false}catch(_){}
   try{if(typeof busy!=='undefined')busy=false}catch(_){}
   try{if(typeof recorder!=='undefined'&&recorder)recorder.onstop=null}catch(_){}
   try{if(typeof stream!=='undefined'&&stream)stream.getTracks().forEach(t=>t.stop())}catch(_){}
   giftActive=false;
 }

 function installDownload(b64,filename){
   if(giftUrl)URL.revokeObjectURL(giftUrl);
   const bin=atob(b64),bytes=new Uint8Array(bin.length);
   for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
   giftUrl=URL.createObjectURL(new Blob([bytes],{type:'text/csv;charset=utf-8'}));
   download.href=giftUrl;
   download.download=filename||'M4_enriched_customer_data.csv';
   download.onclick=function(){status.textContent='Enriched CSV ready — this copy is yours to keep.'};
   box.classList.add('ready');
 }

 input.addEventListener('change',async()=>{
   const file=input.files&&input.files[0];if(!file||giftActive)return;
   box.classList.remove('ready');box.classList.add('busy');status.textContent='analyzing '+file.name+'…';
   try{
     await suspendMeetingMic();
     killCurrentM4Audio();
     if(typeof visual==='function')visual('thinking','Reading the sample and adding a behavioral layer.');
     const fd=new FormData();fd.append('session_id',sessionId);fd.append('data_file',file);
     const r=await fetch('/api/meeting-v2/data-gift',{method:'POST',body:fd,cache:'no-store'});const j=await r.json();
     if(!r.ok)throw new Error(j.error||'Could not analyze CSV');
     if(!j.enriched_csv_base64)throw new Error('Analysis completed but the enriched file was not returned.');
     installDownload(j.enriched_csv_base64,j.enriched_filename);
     status.textContent='Your enriched CSV is ready below. Keep it whether you work with us or not.';
     if(typeof visual==='function')visual('speaking','I added a behavioral layer to your data.');
     killCurrentM4Audio();
     if(j.audio_base64&&typeof play64==='function')await play64(j.audio_base64);
     endMeetingListening();
     if(typeof visual==='function')visual('present','Your enriched data gift is ready to download. Josh has the room.');
   }catch(e){
     giftActive=false;
     try{if(typeof busy!=='undefined')busy=false}catch(_){}
     status.textContent=e.message||'upload failed';
     if(typeof visual==='function')visual('error',status.textContent);
     try{if(typeof started!=='undefined'&&started&&typeof startRecording==='function')setTimeout(startRecording,300)}catch(_){}
   }finally{box.classList.remove('busy');input.value='';}
 });

 window.addEventListener('beforeunload',()=>{if(giftUrl)URL.revokeObjectURL(giftUrl)});
})();
</script>
'''


def enhance(html: str) -> str:
    if 'id="m4-data-gift-ui-style"' in html:
        return html
    return html.replace("</body>", REFINE + "</body>")

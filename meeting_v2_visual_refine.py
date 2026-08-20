"""Small current Meeting UI additions: real CSV data-gift upload and retained-value download."""

# Imported here because this module is already loaded by the production Meeting bootstrap.
# These imports register the upload endpoint and apply the latest prompt guardrails.
import meeting_v2_guardrails  # noqa: F401
import meeting_v2_data_gift  # noqa: F401

REFINE = r'''
<style id="m4-data-gift-ui-style">
#m4DataGift{position:fixed;left:50%;bottom:max(62px,calc(env(safe-area-inset-bottom) + 54px));transform:translateX(-50%);z-index:40;display:flex;align-items:center;gap:8px;opacity:.9;transition:opacity .2s ease;max-width:92vw}
#m4DataGift:hover{opacity:1}
#m4DataGiftLabel,#m4DataGiftDownload{display:inline-flex;align-items:center;gap:7px;padding:8px 11px;border-radius:999px;border:1px solid rgba(166,255,46,.18);background:rgba(5,9,4,.42);color:rgba(218,255,174,.9);font:600 9px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);box-shadow:0 0 24px rgba(153,255,45,.05);cursor:pointer;text-decoration:none;white-space:nowrap}
#m4DataGiftLabel:before,#m4DataGiftDownload:before{content:'';width:6px;height:6px;border-radius:50%;background:#a6ff2e;box-shadow:0 0 10px rgba(166,255,46,.65)}
#m4DataGiftDownload{display:none;border-color:rgba(166,255,46,.35);background:rgba(12,22,7,.68);box-shadow:0 0 30px rgba(153,255,45,.12)}
#m4DataGift.ready #m4DataGiftDownload{display:inline-flex}
#m4DataGift.ready #m4DataGiftLabel{display:none}
#m4DataGiftInput{display:none}
#m4DataGiftStatus{max-width:48vw;color:rgba(229,244,218,.68);font:500 9px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.04em}
#m4DataGift.busy #m4DataGiftLabel{pointer-events:none;opacity:.55}
@media(max-width:600px){#m4DataGift{bottom:max(58px,calc(env(safe-area-inset-bottom) + 50px));width:92vw;justify-content:center;flex-wrap:wrap}#m4DataGiftStatus{max-width:60vw;font-size:8px;text-align:center}}
</style>
<div id="m4DataGift" aria-label="M4 data gift upload">
  <label id="m4DataGiftLabel" for="m4DataGiftInput">Upload CSV</label>
  <input id="m4DataGiftInput" type="file" accept=".csv,text/csv">
  <a id="m4DataGiftDownload" href="#" download>Download enriched CSV</a>
  <span id="m4DataGiftStatus">anonymized test data only</span>
</div>
<script id="m4-data-gift-ui-script">
(function(){
 const box=document.getElementById('m4DataGift'), input=document.getElementById('m4DataGiftInput'), status=document.getElementById('m4DataGiftStatus'), download=document.getElementById('m4DataGiftDownload');
 if(!box||!input||!download)return;
 let giftUrl=null;
 function installDownload(b64,filename){
   if(giftUrl)URL.revokeObjectURL(giftUrl);
   const bin=atob(b64), bytes=new Uint8Array(bin.length);
   for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
   giftUrl=URL.createObjectURL(new Blob([bytes],{type:'text/csv;charset=utf-8'}));
   download.href=giftUrl; download.download=filename||'M4_enriched_customer_data.csv';
   box.classList.add('ready');
 }
 input.addEventListener('change',async()=>{
   const file=input.files&&input.files[0]; if(!file)return;
   box.classList.remove('ready'); box.classList.add('busy'); status.textContent='analyzing '+file.name+'…';
   try{
     if(typeof visual==='function')visual('thinking','Reading the sample and adding a behavioral layer.');
     const fd=new FormData(); fd.append('session_id',sessionId); fd.append('data_file',file);
     const r=await fetch('/api/meeting-v2/data-gift',{method:'POST',body:fd,cache:'no-store'}); const j=await r.json();
     if(!r.ok)throw new Error(j.error||'Could not analyze CSV');
     if(j.enriched_csv_base64)installDownload(j.enriched_csv_base64,j.enriched_filename);
     status.textContent='your enriched file is ready to keep';
     if(typeof visual==='function')visual('speaking','I added a behavioral layer to your data.');
     if(j.audio_base64&&typeof play64==='function')await play64(j.audio_base64);
     setTimeout(()=>{if(typeof visual==='function')visual('present','Your data gift is ready.');},600);
   }catch(e){status.textContent=e.message||'upload failed';if(typeof visual==='function')visual('error',status.textContent)}
   finally{box.classList.remove('busy');input.value='';}
 });
 window.addEventListener('beforeunload',()=>{if(giftUrl)URL.revokeObjectURL(giftUrl)});
})();
</script>
'''


def enhance(html: str) -> str:
    if 'id="m4-data-gift-ui-style"' in html:
        return html
    return html.replace("</body>", REFINE + "</body>")

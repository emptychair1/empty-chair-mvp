"""Small current Meeting UI additions: real CSV data-gift upload."""

REFINE = r'''
<style id="m4-data-gift-ui-style">
#m4DataGift{position:fixed;left:50%;bottom:max(62px,calc(env(safe-area-inset-bottom) + 54px));transform:translateX(-50%);z-index:40;display:flex;align-items:center;gap:8px;opacity:.86;transition:opacity .2s ease}
#m4DataGift:hover{opacity:1}
#m4DataGiftLabel{display:inline-flex;align-items:center;gap:7px;padding:8px 11px;border-radius:999px;border:1px solid rgba(166,255,46,.18);background:rgba(5,9,4,.42);color:rgba(218,255,174,.88);font:600 9px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);box-shadow:0 0 24px rgba(153,255,45,.05);cursor:pointer}
#m4DataGiftLabel:before{content:'';width:6px;height:6px;border-radius:50%;background:#a6ff2e;box-shadow:0 0 10px rgba(166,255,46,.65)}
#m4DataGiftInput{display:none}
#m4DataGiftStatus{max-width:48vw;color:rgba(229,244,218,.66);font:500 9px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.04em}
#m4DataGift.busy #m4DataGiftLabel{pointer-events:none;opacity:.55}
@media(max-width:600px){#m4DataGift{bottom:max(58px,calc(env(safe-area-inset-bottom) + 50px));width:92vw;justify-content:center}#m4DataGiftStatus{max-width:50vw;font-size:8px}}
</style>
<div id="m4DataGift" aria-label="M4 data gift upload">
  <label id="m4DataGiftLabel" for="m4DataGiftInput">Upload CSV</label>
  <input id="m4DataGiftInput" type="file" accept=".csv,text/csv">
  <span id="m4DataGiftStatus">anonymized test data only</span>
</div>
<script id="m4-data-gift-ui-script">
(function(){
 const box=document.getElementById('m4DataGift'), input=document.getElementById('m4DataGiftInput'), status=document.getElementById('m4DataGiftStatus');
 if(!box||!input)return;
 input.addEventListener('change',async()=>{
   const file=input.files&&input.files[0]; if(!file)return;
   box.classList.add('busy'); status.textContent='analyzing '+file.name+'…';
   try{
     if(typeof window.visual==='function')window.visual('thinking','Reading the sample and looking for useful structure.');
     const fd=new FormData(); fd.append('session_id',window.sessionId||sessionId); fd.append('data_file',file);
     const r=await fetch('/api/meeting-v2/data-gift',{method:'POST',body:fd,cache:'no-store'}); const j=await r.json();
     if(!r.ok)throw new Error(j.error||'Could not analyze CSV');
     status.textContent='data gift complete';
     if(typeof window.visual==='function')window.visual('speaking','I found something useful in the data.');
     if(j.audio_base64&&typeof window.play64==='function')await window.play64(j.audio_base64); else if(j.audio_base64&&typeof play64==='function')await play64(j.audio_base64);
     setTimeout(()=>{if(typeof window.visual==='function')window.visual('listening','Josh has the room.');},800);
   }catch(e){status.textContent=e.message||'upload failed';if(typeof window.visual==='function')window.visual('error',status.textContent)}
   finally{box.classList.remove('busy');input.value='';}
 });
})();
</script>
'''


def enhance(html: str) -> str:
    if 'id="m4-data-gift-ui-style"' in html:
        return html
    return html.replace("</body>", REFINE + "</body>")

const $=id=>document.getElementById(id);
let current=null, job=null;

function msg(id,t){$(id).textContent=t}
function loadSource(d){
  current=d;
  $("workspace").classList.remove("hide");
  $("name").textContent=d.filename;
  const isAudio=/\.(mp3|wav|flac|m4a|aac|ogg)$/i.test(d.filename);
  if(isAudio){
    $("video").classList.add("hide"); $("audio").classList.remove("hide");
    $("audio").src="/api/preview?path="+encodeURIComponent(d.path); $("audio").load();
  }else{
    $("audio").classList.add("hide"); $("video").classList.remove("hide");
    $("video").src="/api/preview?path="+encodeURIComponent(d.path); $("video").load();
  }
}

$("fileTab").onclick=()=>{$("fileTab").classList.add("active");$("ytTab").classList.remove("active");$("uploadBox").classList.remove("hide");$("ytBox").classList.add("hide")}
$("ytTab").onclick=()=>{$("ytTab").classList.add("active");$("fileTab").classList.remove("active");$("ytBox").classList.remove("hide");$("uploadBox").classList.add("hide")}

$("file").onchange=async e=>{
  const f=e.target.files[0]; if(!f)return; msg("fs","Uploading...");
  const d=new FormData(); d.append("file",f);
  const r=await fetch("/api/upload",{method:"POST",body:d}); const j=await r.json();
  if(!r.ok)return msg("fs",j.detail||"Upload failed.");
  msg("fs","Loaded. You can extract now OR separate with AI."); loadSource(j);
}

$("ytbtn").onclick=async()=>{
  msg("ys","Downloading YouTube video locally..."); $("ytbtn").disabled=true;
  try{
    const d=new FormData(); d.append("url",$("url").value);
    const r=await fetch("/api/youtube",{method:"POST",body:d}); const j=await r.json();
    if(!r.ok)throw Error(j.detail||"YouTube download failed.");
    msg("ys","Downloaded locally."); loadSource(j);
  }catch(e){msg("ys",e.message)} finally{$("ytbtn").disabled=false}
}

$("extract").onclick=async()=>{
  if(!current)return;
  msg("extractStatus","Extracting audio...");
  const d=new FormData();
  d.append("source_path",current.path); d.append("output_format",$("format").value);
  d.append("bitrate",$("bitrate").value); d.append("start",$("start").value); d.append("end",$("end").value);
  d.append("normalize",$("normExtract").checked);
  const r=await fetch("/api/extract",{method:"POST",body:d}); const j=await r.json();
  if(!r.ok)return msg("extractStatus",j.detail||"Extraction failed.");
  msg("extractStatus","Audio extracted. You can download it OR use it as the AI separation source.");
  current={...current,filename:j.filename,path:j.path,size:0};
  $("video").classList.add("hide"); $("audio").classList.remove("hide");
  $("audio").src="/api/preview?path="+encodeURIComponent(j.path); $("audio").load();
  $("result").classList.remove("hide");
  $("result").innerHTML='<b>Extracted audio:</b> '+j.filename+'<br><br><a class="download" href="'+j.url+'">⬇ Download Extracted Audio</a>';
}

$("separate").onclick=async()=>{
  if(!current)return;
  msg("sepStatus","Starting AI separation..."); $("separate").disabled=true;
  const d=new FormData(); d.append("source_path",current.path); d.append("model",$("model").value); d.append("device",$("deviceSelect").value);
  const r=await fetch("/api/separate",{method:"POST",body:d}); const j=await r.json();
  if(!r.ok){msg("sepStatus",j.detail||"Separation failed.");$("separate").disabled=false;return}
  job=j.job_id; $("device").textContent="Device: "+j.device.toUpperCase(); poll();
}

async function poll(){
  const r=await fetch("/api/job/"+job); const j=await r.json();
  $("bar").style.width=(j.progress||0)+"%"; msg("sepStatus",j.message||"Working...");
  if(j.status==="complete"){
    $("mixer").classList.remove("hide"); $("export").classList.remove("hide");
    for(const s of ["vocals","drums","bass","other"]){$("a"+s).src="/api/stem/"+job+"/"+s;$("a"+s).load()}
    $("separate").disabled=false; return;
  }
  if(j.status==="error"){$("separate").disabled=false;return}
  setTimeout(poll,1500);
}

for(const [id,out] of [["vocals","vo"],["drums","dr"],["bass","ba"],["other","ot"]]){
  $(id).oninput=e=>$(out).textContent=e.target.value+"%";
}
$("pitch").oninput=e=>{
  const n=+e.target.value;
  $("pitchText").textContent=(n>0?"+":"")+n+" semitones "+(n===0?"(original key)":(n<0?"(lower)":"(higher)"));
}

async function exportMix(karaoke){
  if(!job)return;
  msg("exportStatus","Rendering final mix...");
  const d=new FormData();
  d.append("job_id",job); d.append("mode",karaoke?"karaoke":"custom_mix");
  d.append("vocals",karaoke?0:$("vocals").value); d.append("drums",$("drums").value);
  d.append("bass",$("bass").value); d.append("other",$("other").value);
  d.append("pitch",$("pitch").value); d.append("output_format",$("outFormat").value);
  d.append("bitrate",$("outBitrate").value); d.append("normalize",$("normFinal").checked);
  d.append("start",$("start").value); d.append("end",$("end").value);
  const r=await fetch("/api/export",{method:"POST",body:d}); const j=await r.json();
  if(!r.ok)return msg("exportStatus",j.detail||"Export failed.");
  msg("exportStatus","Done.");
  $("result").classList.remove("hide");
  $("result").innerHTML='<b>Final audio ready:</b> '+j.filename+'<br><br><a class="download" href="'+j.url+'">⬇ Download Final Audio</a>';
}
$("karaoke").onclick=()=>exportMix(true);
$("full").onclick=()=>exportMix(false);

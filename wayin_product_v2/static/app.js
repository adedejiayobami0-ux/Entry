
const $=id=>document.getElementById(id);
let csrf=document.querySelector('meta[name="csrf-token"]')?.content||"";
let trip=[];
let authMode="login";
let session={authenticated:false};

document.querySelectorAll(".chip").forEach(b=>b.onclick=()=>b.setAttribute("aria-pressed",b.getAttribute("aria-pressed")!=="true"));
const needs=()=>[...document.querySelectorAll(".chip[aria-pressed=true]")].map(x=>x.dataset.need);

async function api(url,opts={}){
 const headers={"Content-Type":"application/json",...(opts.headers||{})};
 if(opts.method&&opts.method!=="GET"&&csrf)headers["X-CSRF-Token"]=csrf;
 const r=await fetch(url,{...opts,headers,credentials:"same-origin"});
 const text=await r.text(); let d={};
 try{d=text?JSON.parse(text):{}}catch{d={error:text||"Unexpected response"}}
 if(!r.ok)throw new Error(d.error||`Request failed (${r.status})`);
 return d;
}
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
function cityCode(v){const x=v.trim().toUpperCase();return x.length===3?x:({"SEATTLE":"SEA","CHICAGO":"CHI","SAN DIEGO":"SAN","NEW YORK":"NYC","LOS ANGELES":"LAX","MIAMI":"MIA","BOSTON":"BOS","ATLANTA":"ATL","DALLAS":"DFW","LONDON":"LON","PARIS":"PAR"}[x]||x.slice(0,3));}

$("searchBtn").onclick=async()=>{
 $("searchStatus").textContent="Searching live providers…";
 $("searchBtn").disabled=true;
 try{
  const d=await api("/api/live-search",{method:"POST",body:JSON.stringify({
   origin:$("origin").value, destination:$("destination").value,
   city_code:cityCode($("destination").value), departure_date:$("depart").value,
   return_date:$("returnDate").value, adults:Number($("adults").value||1),
   category:$("category").value, traveler_type:$("traveler").value, needs:needs()
  })});
  renderResults(d.results);
  const missing=[];
  if(!d.configured.flights_hotels)missing.push("Amadeus keys needed for flights/hotels");
  if(!d.configured.events)missing.push("Ticketmaster key needed for events");
  $("searchStatus").textContent=d.results.length?`Found ${d.results.length} live result(s). ${missing.join(" · ")}`:`No live results. ${missing.join(" · ")}`;
 }catch(e){$("searchStatus").textContent=e.message}
 finally{$("searchBtn").disabled=false}
};
function renderResults(items){
 $("resultCount").textContent=`${items.length} result(s)`;
 $("results").innerHTML=items.length?items.map((x,i)=>`<article class="card result">
 <div class="row"><span class="badge">${esc(x.type)}</span><span class="source">${esc(x.source||"WayIn")}</span></div>
 <h3>${esc(x.name)}</h3><div class="muted">${esc(x.location)}</div><p>${esc(x.summary)}</p>
 <div class="row"><b>${esc(x.price)}</b><button class="btn primary" data-add="${i}">Add to trip</button></div>
 ${x.booking_url?`<p><a href="${esc(x.booking_url)}" target="_blank" rel="noopener">View / book with provider</a></p>`:""}
 </article>`).join(""):`<div class="card muted">No live results returned.</div>`;
 document.querySelectorAll("[data-add]").forEach(b=>b.onclick=()=>addTrip(items[Number(b.dataset.add)]));
}
function addTrip(x){
 if(trip.some(i=>i.id===x.id))return;
 trip.push({...x,status:"selected"});renderTrip();
}
function renderTrip(){
 $("tripCount").textContent=`${trip.length} item${trip.length===1?"":"s"}`;
 $("tripItems").innerHTML=trip.length?trip.map((x,i)=>`<div class="tripitem"><b>${esc(x.type)} · ${esc(x.name)}</b><div class="muted">${esc(x.location)} · ${esc(x.price)}</div><button class="btn" data-remove="${i}" style="margin-top:5px">Remove</button></div>`).join(""):`<p class="muted">Add results to build the shared itinerary.</p>`;
 document.querySelectorAll("[data-remove]").forEach(b=>b.onclick=()=>{trip.splice(Number(b.dataset.remove),1);renderTrip()});
}

$("chatForm").onsubmit=async e=>{
 e.preventDefault();const msg=$("chatInput").value.trim();if(!msg)return;
 $("chatlog").insertAdjacentHTML("beforeend",`<div class="bubble me">${esc(msg)}</div>`);$("chatInput").value="";
 try{const d=await api("/api/ai-chat",{method:"POST",body:JSON.stringify({message:msg,trip})});$("chatlog").insertAdjacentHTML("beforeend",`<div class="bubble">${esc(d.reply)}</div>`)}
 catch(err){$("chatlog").insertAdjacentHTML("beforeend",`<div class="bubble bad">${esc(err.message)}</div>`)}
 $("chatlog").scrollTop=$("chatlog").scrollHeight;
};

async function refreshSession(){
 try{const d=await api("/api/session");session=d;csrf=d.csrf_token||csrf;$("login").hidden=d.authenticated;$("signup").hidden=d.authenticated;$("logout").hidden=!d.authenticated;$("user").textContent=d.authenticated?d.email:"";}
 catch{}
}
function openAuth(m){authMode=m;$("auth").style.display="grid";$("authTitle").textContent=m==="register"?"Create account":"Log in";$("authSubmit").textContent=$("authTitle").textContent;$("authError").textContent=""}
$("login").onclick=()=>openAuth("login");$("signup").onclick=()=>openAuth("register");$("cancelAuth").onclick=()=>$("auth").style.display="none";
$("authForm").onsubmit=async e=>{
 e.preventDefault();try{const d=await api(authMode==="register"?"/api/register":"/api/login",{method:"POST",body:JSON.stringify({email:$("authEmail").value,password:$("authPassword").value})});csrf=d.csrf_token;$("auth").style.display="none";await refreshSession()}catch(err){$("authError").textContent=err.message}
};
$("logout").onclick=async()=>{await api("/api/logout",{method:"POST",body:"{}"});await refreshSession()};

$("shareBtn").onclick=async()=>{
 $("shareStatus").className="status";$("shareStatus").textContent="";
 if(!session.authenticated){openAuth("login");$("shareStatus").textContent="Log in first, then click Send trip again.";return}
 const emails=$("emails").value.split(",").map(x=>x.trim()).filter(Boolean);
 const phones=$("phones").value.split(",").map(x=>x.trim()).filter(Boolean);
 try{
  const d=await api("/api/share-trip",{method:"POST",body:JSON.stringify({title:`${$("destination").value} trip`,items:trip,emails,phones})});
  $("shareStatus").className="status good";
  $("shareStatus").textContent=`Sent ${d.sent_email} email(s) and ${d.sent_sms} text(s). ${d.warnings?.join(" · ")||""}`;
 }catch(e){$("shareStatus").className="status bad";$("shareStatus").textContent=e.message}
};
refreshSession();

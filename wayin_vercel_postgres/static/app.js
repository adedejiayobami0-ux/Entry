let csrfToken = window.WAYIN_CSRF;
let authMode = "login";
let sessionState = {authenticated:false,email:null};
let lastSearch = null;

const $ = (id) => document.getElementById(id);
const chips = [...document.querySelectorAll(".chip")];

chips.forEach(chip => chip.addEventListener("click", () => {
  chip.setAttribute("aria-pressed", chip.getAttribute("aria-pressed") !== "true");
}));

$("travelerType").addEventListener("change", () => {
  const labels = {
    individual:"Planning just for you.",
    couple:"Planning for two travelers.",
    single_parent:"We’ll prioritize kid-friendly logistics without forgetting the parent.",
    family:"We’ll optimize for the needs of the whole family.",
    group:"We’ll balance different preferences across the group."
  };
  $("travelerHint").textContent = labels[$("travelerType").value] || "";
});

function selectedNeeds(){
  return chips.filter(c => c.getAttribute("aria-pressed")==="true").map(c => c.dataset.need);
}

async function api(path, options={}){
  const headers = {"Content-Type":"application/json", ...(options.headers||{})};
  if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(path, {...options, headers});
  const data = await res.json().catch(()=>({error:"Unexpected server response."}));
  if (!res.ok) throw new Error(data.error || "Request failed.");
  return data;
}

function currentQuery(){
  return {
    destination:$("destination").value.trim(),
    traveler_type:$("travelerType").value,
    category:$("category").value,
    needs:selectedNeeds()
  };
}

function escapeHtml(value){
  return String(value).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}

function renderResults(data){
  lastSearch = data.query;
  $("resultsTitle").textContent = `${data.query.traveler_label} matches`;
  $("querySummary").textContent = `${data.query.destination || "Any destination"} · ${data.query.category} · ${data.query.needs.length ? data.query.needs.join(" · ") : "No extra needs"}`;
  const list = data.results;
  if(!list.length){
    $("results").innerHTML = `<div class="empty">No exact results yet. Try a broader destination or category.</div>`;
    return;
  }
  $("results").innerHTML = list.map(item => `
    <article class="card result">
      <div class="cover"><span class="badge">${escapeHtml(item.type)}</span><span class="badge">${item.fit_score}% fit</span></div>
      <div class="body">
        <h3>${escapeHtml(item.name)}</h3>
        <div class="meta">${escapeHtml(item.location)} · ${escapeHtml(item.price)}</div>
        <p>${escapeHtml(item.summary)}</p>
        <div class="fit"><span>${data.query.traveler_label} fit</span><strong>${item.fit_score}%</strong></div>
        <div class="tags">${item.matched_needs.map(n=>`<span class="tag">✓ ${escapeHtml(n)}</span>`).join("") || `<span class="tag">General match</span>`}</div>
        ${item.unconfirmed_needs.length ? `<div class="missing">Not confirmed: ${item.unconfirmed_needs.map(escapeHtml).join(", ")}</div>` : ""}
      </div>
    </article>
  `).join("");
}

async function runSearch(){
  $("searchBtn").disabled = true;
  try{
    const data = await api("/api/search",{method:"POST",body:JSON.stringify(currentQuery())});
    renderResults(data);
  }catch(err){
    $("results").innerHTML = `<div class="empty">${escapeHtml(err.message)}</div>`;
  }finally{
    $("searchBtn").disabled = false;
  }
}

$("searchBtn").addEventListener("click", runSearch);

function openAuth(mode){
  authMode = mode;
  $("authTitle").textContent = mode==="register" ? "Create account" : "Log in";
  $("authSubmit").textContent = mode==="register" ? "Create account" : "Log in";
  $("authPassword").autocomplete = mode==="register" ? "new-password" : "current-password";
  $("authError").textContent = "";
  $("authBackdrop").classList.add("open");
  setTimeout(()=>$("authEmail").focus(),0);
}
function closeAuth(){ $("authBackdrop").classList.remove("open"); }
$("loginBtn").addEventListener("click",()=>openAuth("login"));
$("signupBtn").addEventListener("click",()=>openAuth("register"));
$("closeAuth").addEventListener("click",closeAuth);
$("authBackdrop").addEventListener("click",e=>{if(e.target===$("authBackdrop"))closeAuth();});

$("authForm").addEventListener("submit", async e=>{
  e.preventDefault();
  $("authError").textContent = "";
  $("authSubmit").disabled = true;
  try{
    const endpoint = authMode==="register" ? "/api/register" : "/api/login";
    const data = await api(endpoint,{
      method:"POST",
      body:JSON.stringify({email:$("authEmail").value,password:$("authPassword").value})
    });
    csrfToken = data.csrf_token;
    closeAuth();
    await refreshSession();
  }catch(err){
    $("authError").textContent = err.message;
  }finally{
    $("authSubmit").disabled = false;
  }
});

async function refreshSession(){
  const data = await api("/api/session");
  sessionState = data;
  csrfToken = data.csrf_token;
  const signed = data.authenticated;
  $("userPill").hidden = !signed;
  $("savedBtn").hidden = !signed;
  $("saveSearchBtn").hidden = !signed;
  $("logoutBtn").hidden = !signed;
  $("loginBtn").hidden = signed;
  $("signupBtn").hidden = signed;
  if(signed) $("userPill").textContent = data.email;
  if(!signed) $("savedPanel").classList.remove("show");
}

$("logoutBtn").addEventListener("click",async()=>{
  await api("/api/logout",{method:"POST",body:"{}"});
  await refreshSession();
});

$("saveSearchBtn").addEventListener("click",async()=>{
  try{
    const q = lastSearch || currentQuery();
    await api("/api/save-search",{method:"POST",body:JSON.stringify(q)});
    $("saveSearchBtn").textContent = "Saved ✓";
    setTimeout(()=>$("saveSearchBtn").textContent="Save this search",1200);
  }catch(err){ alert(err.message); }
});

$("savedBtn").addEventListener("click",async()=>{
  try{
    const data = await api("/api/saved-searches");
    $("savedPanel").classList.add("show");
    $("savedList").innerHTML = data.items.length ? data.items.map(item=>`
      <div class="saved-item">
        <div><b>${escapeHtml(item.destination || "Any destination")}</b><div class="meta">${escapeHtml(item.category)} · ${escapeHtml(item.traveler_type.replaceAll("_"," "))}</div></div>
        <div class="meta">${item.needs.map(escapeHtml).join(", ") || "No extra needs"}</div>
      </div>`).join("") : `<div class="meta">No saved searches yet.</div>`;
    $("savedPanel").scrollIntoView({behavior:"smooth"});
  }catch(err){ alert(err.message); }
});

refreshSession();
runSearch();

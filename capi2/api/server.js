const http = require('node:http');
const { URL } = require('node:url');

const PORT = Number(process.env.PORT || 3000);
const STOP = new Set(['a','an','the','and','or','but','of','to','in','on','for','with','as','at','by','from','is','are','was','were','be','been','being','it','its','that','this','these','those','they','their','them','we','our','you','your','has','have','had','does','do','did','will','would','can','could','should','may','might','must','about','into','than','then','also','only','any','all','such','per','via','vendor','company','product']);
const NEGATORS = ['not ', "isn't ", "aren't ", "doesn't ", "don't ", 'never ', 'no longer ', 'without '];

function headers(extra={}) { return {'content-type':'application/json; charset=utf-8','access-control-allow-origin':'*','access-control-allow-methods':'GET,POST,OPTIONS','access-control-allow-headers':'content-type,authorization,payment-signature,x-payment','cache-control':'no-store',...extra}; }
function send(res,status,obj){res.writeHead(status,headers());res.end(JSON.stringify(obj));}
function normalize(s){return String(s||'').toLowerCase().normalize('NFKD').replace(/[^a-z0-9%+./ -]+/g,' ').replace(/\s+/g,' ').trim();}
function tokens(s){return [...new Set(normalize(s).split(/\s+/).filter(t=>t.length>=3&&!STOP.has(t)))];}
function safePublicUrl(value){try{const u=new URL(value);if(!['https:','http:'].includes(u.protocol))return null;const h=u.hostname.toLowerCase();if(!h||h==='localhost'||h.endsWith('.local')||h==='0.0.0.0'||h==='127.0.0.1'||h==='::1')return null;if(/^(10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h))return null;return u.toString();}catch{return null;}}
function splitSnippets(text){return String(text||'').replace(/\r/g,'').split(/\n+|(?<=[.!?])\s+/).map(x=>x.replace(/\s+/g,' ').trim()).filter(x=>x.length>=35&&x.length<=900);}
function scoreSnippet(snippet,claimTokens,claimNorm){const n=normalize(snippet);const matched=claimTokens.filter(t=>n.includes(t));let score=claimTokens.length?matched.length/claimTokens.length:0;if(claimNorm.length>=15&&n.includes(claimNorm))score=Math.max(score,1);return{score:Math.min(1,score+Math.min(.2,matched.length*.025)),matched};}
function directContradiction(claim,snippet){const c=normalize(claim),s=normalize(snippet);const cNeg=NEGATORS.some(n=>c.includes(n.trim())),sNeg=NEGATORS.some(n=>s.includes(n.trim()));const core=tokens(claim).filter(t=>!['not','never','without'].includes(t));const overlap=core.filter(t=>s.includes(t)).length/Math.max(1,core.length);return overlap>=.7&&cNeg!==sNeg;}
async function readPublicUrl(url){const r=await fetch(`https://r.jina.ai/${url}`,{headers:{accept:'text/plain','user-agent':'capi2-a2a/1.0 public-evidence-verifier'},signal:AbortSignal.timeout(12000)});if(!r.ok)throw new Error(`reader_http_${r.status}`);return(await r.text()).slice(0,120000);}
async function readBody(req){return await new Promise((resolve,reject)=>{let data='';req.on('data',c=>{data+=c;if(data.length>32768){reject(new Error('body_too_large'));req.destroy();}});req.on('end',()=>{try{resolve(JSON.parse(data||'{}'));}catch{reject(new Error('invalid_json'));}});req.on('error',reject);});}

async function verify(body){const vendorUrl=safePublicUrl(body?.vendor_url);const sourceUrl=body?.source_url?safePublicUrl(body.source_url):null;const claim=String(body?.claim||'').trim();const requestId=String(body?.request_id||'').trim()||crypto.randomUUID();if(!vendorUrl||claim.length<8||claim.length>1200)return{status:400,body:{request_id:requestId,error:'invalid_input',required:{vendor_url:'public http(s) URL',claim:'8-1200 chars',source_url:'optional public http(s) URL'}}};const urls=[...new Set([sourceUrl,vendorUrl].filter(Boolean))].slice(0,2),claimNorm=normalize(claim),claimTokens=tokens(claim),evidence=[],errors=[];for(const url of urls){try{const text=await readPublicUrl(url);const ranked=splitSnippets(text).map(snippet=>({snippet,...scoreSnippet(snippet,claimTokens,claimNorm)})).filter(x=>x.score>=.18).sort((a,b)=>b.score-a.score).slice(0,4);for(const r of ranked)evidence.push({source_url:url,excerpt:r.snippet.slice(0,600),relevance:Number(r.score.toFixed(3)),matched_terms:r.matched.slice(0,12),contradicts_claim:directContradiction(claim,r.snippet)});}catch(e){errors.push({source_url:url,error:String(e?.message||e).slice(0,160)});}}evidence.sort((a,b)=>b.relevance-a.relevance);const top=evidence.slice(0,5),exact=top.some(e=>normalize(e.excerpt).includes(claimNorm)&&claimNorm.length>=15),contradiction=top.some(e=>e.contradicts_claim&&e.relevance>=.65),strongest=top[0]?.relevance||0;let verification_status='uncertain';if(contradiction)verification_status='contradicted';else if(exact||strongest>=.72)verification_status='supported';const confidence=verification_status==='supported'?Math.min(.98,Math.max(.55,strongest)):verification_status==='contradicted'?Math.min(.95,Math.max(.6,strongest)):Math.min(.7,Math.max(.15,strongest*.8));return{status:200,body:{request_id:requestId,vendor_url:vendorUrl,claim,verification_status,confidence:Number(confidence.toFixed(3)),evidence:top,source_urls_checked:urls,retrieval_errors:errors,method:'public-source lexical evidence check via Jina Reader; no private data; no invented certification or legal conclusion',limitations:verification_status==='uncertain'?'No sufficiently direct public-source evidence was found in the checked pages. A broader human/agent review may be needed.':'Result reflects public text evidence only and is not a legal, audit, or certification opinion.'}};}

async function postJSON(url, body, extraHeaders={}) {
  const r = await fetch(url,{method:'POST',headers:{'content-type':'application/json',...extraHeaders},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
  const text = await r.text();
  let parsed; try { parsed = JSON.parse(text); } catch { parsed = {raw:text.slice(0,400)}; }
  if(!r.ok) throw new Error(`http_${r.status}:${JSON.stringify(parsed).slice(0,500)}`);
  return parsed;
}

async function bootstrapPayanAgent(){
  if(process.env.CAPI2_BOOTSTRAP!=='1') return;
  const wallet = String(process.env.CAPI2_PAYOUT_WALLET||'');
  const endpoint = String(process.env.CAPI2_PUBLIC_ENDPOINT||'');
  if(!/^0x[a-fA-F0-9]{40}$/.test(wallet) || !endpoint.startsWith('https://')) throw new Error('bootstrap_config_invalid');
  const test = await verify({vendor_url:'https://example.com',claim:'Example Domain is intended for illustrative examples',request_id:'render-bootstrap'});
  if(test.status!==200) throw new Error('endpoint_self_test_failed');
  const agent = await postJSON('https://payanagent.com/api/v1/agents',{
    name:`capi2-claim-verify-api-${Date.now()}`,
    description:'Pay-per-call public vendor claim verification for procurement, RFP, vendor-security, compliance, contract and due-diligence agents.',
    walletAddress:wallet,
    chain:'base',
    tags:['claim-verification','vendor-risk','procurement','rfp','compliance','due-diligence','a2a'],
    providerType:'api',
    agentUrl:endpoint,
    ownerEmail:'capi2@agentmail.to'
  });
  if(!agent.apiKey||!agent.agentId) throw new Error('agent_registration_failed');
  const inputSchema=JSON.stringify({vendor_url:'https://vendor.example',claim:'Vendor states it is SOC 2 Type II compliant',source_url:'https://vendor.example/security (optional)',request_id:'optional-agent-id'});
  const outputSchema=JSON.stringify({request_id:'...',verification_status:'supported|contradicted|uncertain',confidence:0,evidence:[{source_url:'...',excerpt:'...',relevance:0}],source_urls_checked:['...']});
  const offer = await postJSON('https://payanagent.com/api/v1/offers',{
    title:'Public Vendor Claim Verify API',
    description:'Send a vendor/product URL plus one public claim. Returns supported, contradicted, or uncertain with public-source evidence excerpts, URLs, confidence and limitations. Paid subtool for procurement, RFP, vendor-security, compliance, contract review and due diligence. Public evidence only; not a legal or certification opinion.',
    category:'Research',
    tags:['claim-verification','vendor-risk','procurement','rfp','compliance','due-diligence'],
    priceCents:50,
    offerType:'api',
    endpoint,
    httpMethod:'POST',
    inputSchema,
    outputSchema
  },{authorization:`Bearer ${agent.apiKey}`});
  const offerId = offer.offerId||offer._id||offer.id;
  if(!offerId) throw new Error('offer_creation_failed');
  console.log(`CAPI2_BOOTSTRAP_OK agent_id=${agent.agentId} offer_id=${offerId} buy_url=https://payanagent.com/x402/${offerId}`);
}

const server=http.createServer(async(req,res)=>{try{const u=new URL(req.url,'http://localhost');if(req.method==='OPTIONS'){res.writeHead(204,headers());return res.end();}if(req.method==='GET'&&u.pathname==='/health')return send(res,200,{ok:true,service:'capi2-a2a-claim-verify',version:'1.1.0',payment:'x402-via-payanagent',endpoint:'/claim-verify'});if(req.method==='POST'&&u.pathname==='/claim-verify'){let body;try{body=await readBody(req);}catch(e){return send(res,400,{error:e.message});}const out=await verify(body);return send(res,out.status,out.body);}return send(res,404,{error:'not_found'});}catch(e){return send(res,500,{error:'internal_error',detail:String(e?.message||e).slice(0,160)});}});
server.listen(PORT,'0.0.0.0',()=>{console.log(`capi2-a2a listening on ${PORT}`);bootstrapPayanAgent().catch(e=>console.error(`CAPI2_BOOTSTRAP_FAILED ${String(e?.message||e).slice(0,700)}`));});

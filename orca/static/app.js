const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[character]));

const studioNodeID = String(globalThis.ORCA_STUDIO_NODE || '').trim().toUpperCase();
if (/^[A-Z0-9_-]{1,24}$/.test(studioNodeID) && studioNodeID !== 'ANVIL') {
  document.title = `${studioNodeID} Studio`;
  const brand = document.querySelector('.brand');
  if (brand) {
    brand.querySelector('.brand-mark').textContent = studioNodeID.slice(0, 1);
    brand.querySelector('strong').textContent = studioNodeID;
    brand.querySelector('small').textContent = 'STUDIO';
  }
  document.querySelector('.primary-nav')?.setAttribute('aria-label', `${studioNodeID} Studio`);
}

const mutationKey = () => globalThis.crypto?.randomUUID?.()
  || `orca-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const mutationControlSelector = '#operator-identity,#operator-token,#stop-reason,#toggle-stop,[data-approval],[data-pause-job],[data-job-action]';
let mutationPending = false;
let inferencePending = false;
let activeMode = 'auto';
const chatMemoryKey = 'orca-studio-conversation-v1';
let conversationHistory = [];
function boundedHistory(messages) {
  const kept = []; let size = 0;
  for (const message of messages.slice(-20).reverse()) {
    if (!message || !['user', 'assistant'].includes(message.role) || typeof message.content !== 'string') continue;
    const content = message.content.slice(0, 6000);
    if (!content.trim() || size + content.length > 12000) break;
    kept.unshift({role: message.role, content}); size += content.length;
  }
  return kept;
}
async function rememberConversation(prompt, reply) {
  const pair = [{role: 'user', content: prompt}, {role: 'assistant', content: reply}];
  const previous = conversationHistory;
  conversationHistory = boundedHistory([...conversationHistory,
    ...pair]);
  try { localStorage.setItem(chatMemoryKey, JSON.stringify(conversationHistory)); }
  catch { /* Server archive remains available without browser storage. */ }
  try {
    if (previous.length && !localStorage.getItem('orca-memory-migrated-v1')) {
      let migration = JSON.parse(localStorage.getItem('orca-memory-migration-v1') || 'null');
      if (!migration) {
        migration = {id: mutationKey(), messages: previous};
        localStorage.setItem('orca-memory-migration-v1', JSON.stringify(migration));
      }
      await archiveMessages(migration.id, migration.messages);
      localStorage.setItem('orca-memory-migrated-v1', 'yes');
      localStorage.removeItem('orca-memory-migration-v1');
    }
  } catch { /* An unavailable browser store must not block new server memories. */ }
  try {
    await archiveMessages(mutationKey(), pair);
    $('#memory-hint').textContent = 'Memory: newest 300,000 messages · New chat keeps memory';
  } catch {
    $('#memory-hint').textContent = 'Long-term memory was not saved for this reply. Recent context remains on this device.';
  }
}
async function archiveMessages(requestID, messages) {
  const response = await fetch('/api/memory', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-ORCA-Identity': studioAuth.identity,
      'X-ORCA-Identity-Token': studioAuth.token},
    body: JSON.stringify({request_id: requestID, messages})});
  if (!response.ok) throw Error('Conversation archive unavailable');
}
let inventory = { items: [], locations: [], categories: [], units: [] };
let inventoryAnalysis = null;
let inventoryCountRows = [];
let inventorySystem = null;
let studioAuth = { identity: 'fry', token: '' };
let state = {
  jobs: [], approvals: [], events: [], incidents: [], security_reports: [],
  security_adjudications: [], security_exceptions: [], retention_audits: [],
  agents: [], bots: [], connectors: [], connector_capabilities: [], nodes: [],
  paused_lanes: [], paused_nodes: [], emergency_stop: false, state_revision: 0
};

const routes = {
  auto: {
    service_id: 'kiln_codex', label: 'ORCA · Codex Auto', name: 'ORCA · Codex + local specialists',
    duty: 'Codex handles governed reasoning and coding; ORCA routes tools and approvals; Qwen provides local fallback.',
    node: 'KILN + FORGE', context: 'Conversation memory on'
  },
  photo: {
    label: 'Images · CRUCIBLE', name: 'ORCA Image Studio',
    duty: 'Generate photos and images directly in this conversation. Save any image you want to keep.',
    node: 'FORGE · SDXL', context: 'Native 1024 + Canvas editing'
  },
  video: {
    label: 'Video · CRUCIBLE', name: 'ORCA Motion Studio',
    duty: 'Generate short local MP4 clips from a prompt. Use Canvas to animate an existing image.',
    node: 'FORGE · Wan 2.2', context: 'Text-to-video + image-to-video'
  },
  reason: {
    service_id: 'kiln_codex', bot_id: 'orca', label: 'Codex · KILN',
    name: 'ORCA · Codex', duty: 'Conversation, explanations, research planning and hard reasoning through the governed KILN bridge.',
    node: 'KILN · OpenAI', context: 'ORCA memory + approvals'
  },
  code: {
    service_id: 'kiln_codex', bot_id: 'smith', label: 'Codex · Code',
    name: 'Codex + Qwen fallback', duty: 'Coding, implementation, documentation and repository-scale synthesis under ORCA controls.',
    node: 'KILN + FORGE', context: 'Read-only until approved'
  },
  review: {
    service_id: 'kiln_quench', bot_id: 'quench', label: 'QUENCH · BILLOWS',
    name: 'QUENCH', duty: 'Independent technical, security and verification review on KILN.',
    node: 'KILN · CUDA', context: '4K context'
  },
  engineer: {
    service_id: 'kiln_codex', bot_id: 'smith', label: 'Codex · Engineering',
    name: 'Codex Engineer', duty: 'Tradeoffs, calculations, mechanisms, circuits and failure analysis with deterministic ORCA tools.',
    node: 'KILN + FORGE', context: 'Verified calculators'
  },
  visual: {
    service_id: 'kiln_codex', bot_id: 'orca', label: 'Codex · Visual Direction',
    name: 'Visual Director', duty: 'Structured visual concepts, diagrams, compositions and production briefs.',
    node: 'KILN · OpenAI', context: 'ORCA memory + tools'
  }
};

function syncMutationControls() {
  $$(mutationControlSelector).forEach(control => { control.disabled=mutationPending; });
  document.querySelector('main')?.setAttribute('aria-busy', String(mutationPending));
}
function setMutationPending(pending) { mutationPending = pending; syncMutationControls(); }
const controlAuth = () => ({
  identity: $('#operator-identity')?.value || studioAuth.identity,
  token: $('#operator-token')?.value || studioAuth.token
});

function mutationEnvelope(url,payload,auth){
  const key=mutationKey(),expectedRevision=String(state.state_revision??0),headers=Object.freeze({'Content-Type':'application/json','X-ORCA-Operator-Token':auth.token,'X-ORCA-Identity':auth.identity,'X-ORCA-Identity-Token':auth.token,'Idempotency-Key':key,'X-ORCA-Expected-Revision':expectedRevision});
  return Object.freeze({url,body:JSON.stringify(payload),headers,key,expectedRevision});
}
async function postMutation(url, payload, auth) {
  const envelope=mutationEnvelope(url,payload,auth);
  setMutationPending(true);
  try {
    let response,lastTransportError;
    for(let attempt=0;attempt<2;attempt+=1){
      try { response=await fetch(envelope.url,{method:'POST',headers:envelope.headers,body:envelope.body}); break; }
      catch(error){ lastTransportError=error; }
    }
    if(!response)throw lastTransportError||Error('ORCA transport failed');
    let body;
    try { body=await response.json(); }
    catch { throw Error(`ORCA returned an unreadable response (${response.status})`); }
    if(!response.ok)throw Error(body.error||response.status);
    return body;
  } finally{setMutationPending(false)}
}

async function postInference(prompt, mode = activeMode, history = []) {
  const route = routes[mode];
  const response = await fetch('/api/inference', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-ORCA-Identity': studioAuth.identity,
      'X-ORCA-Identity-Token': studioAuth.token
    },
    body: JSON.stringify({ service_id: route.service_id, bot_id: route.bot_id, prompt, history })
  });
  let body;
  try { body = await response.json(); }
  catch { throw Error(`ORCA returned an unreadable response (${response.status})`); }
  if (!response.ok) throw Error(body.error || `ORCA inference failed (${response.status})`);
  return body;
}

async function postChat(prompt, history, businessJobID = null) {
  const payload = {prompt, history};
  if (businessJobID) payload.business_job_id = businessJobID;
  const response = await fetch('/api/chat', {
    method: 'POST', headers: {'Content-Type': 'application/json',
      'X-ORCA-Identity': studioAuth.identity, 'X-ORCA-Identity-Token': studioAuth.token},
    body: JSON.stringify(payload)
  });
  let body;
  try { body = await response.json(); } catch { throw Error('Studio returned an unreadable reply.'); }
  if (!response.ok) throw Error(body.error || `Chat failed (${response.status})`);
  return body;
}

async function startBusinessWorkflow(workflow) {
  await refresh();
  const job = await postMutation('/api/business/workflows', {
    workflow_id: workflow.id,
    title: workflow.title
  }, controlAuth());
  await refresh();
  return job;
}

async function postProjectPlan(prompt) {
  const response = await fetch('/api/project/plan', {
    method: 'POST', headers: {'Content-Type': 'application/json',
      'X-ORCA-Identity': studioAuth.identity, 'X-ORCA-Identity-Token': studioAuth.token},
    body: JSON.stringify({prompt})
  });
  let body;
  try { body = await response.json(); } catch { throw Error('Studio returned an unreadable project plan.'); }
  if (!response.ok) throw Error(body.error || `Project planning failed (${response.status})`);
  return body;
}

function projectSummary(plan, outcome) {
  const have = plan.inventory_use.length
    ? plan.inventory_use.map(item => `${item.quantity} × ${item.name} (${item.sku})`).join('\n• ')
    : 'No matching parts are recorded in the KILN inventory.';
  const need = plan.missing_parts.map(item => `${item.quantity} × ${item.part} — ${item.reason}`).join('\n• ');
  return `${outcome.message}\n\nOn hand\n• ${have}\n\nStill needed\n• ${need}\n\nThe schematic and editable PCB draft were created. KiCad PCB Editor is open on KILN, and ORCA has stopped so you can edit it.`;
}

function show(id) {
  $$('.view').forEach(view => view.classList.toggle('active', view.id === id));
  $$('.primary-nav [data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === id));
  const titles = {
    studio: ['WORKBENCH', 'Studio'], projects: ['CODING DESK', 'Code'],
    canvas: ['VISUAL LAB', 'Canvas'], inventory: ['BENCH CATALOG', 'Inventory'],
    engineering: ['ENGINEERING DESK', 'Engineering'], operations: ['CONTROL PLANE', 'Operations'],
    business: ['QUASARVOLT SUPPLY', 'Business'],
    'product-builder': ['DESIGN AUTOMATION', 'Product Builder']
  };
  const [kicker, title] = titles[id] || titles.studio;
  $('#workspace-kicker').textContent = kicker;
  $('#workspace-title').textContent = title;
  if (id === 'inventory') loadInventory();
}
function showOps(id) {
  show('operations');
  $$('.ops-view').forEach(view => view.classList.toggle('active', view.id === id));
  $$('[data-ops-view]').forEach(button => button.classList.toggle('active', button.dataset.opsView === id));
}

$$('[data-view]').forEach(button => button.addEventListener('click', () => {
  show(button.dataset.view);
  if (button.dataset.opsView) showOps(button.dataset.opsView);
}));
$$('[data-ops-view]').forEach(button => button.addEventListener('click', () => showOps(button.dataset.opsView)));

function selectMode(mode) {
  activeMode = mode;
  const route = routes[mode];
  $$('[data-mode]').forEach(button => button.classList.toggle('active', button.dataset.mode === mode));
  $('#active-route').textContent = route.label;
  $('#route-name').textContent = route.name;
  $('#route-duty').textContent = route.duty;
  $('#route-node').textContent = route.node;
  $('#route-context').textContent = route.context;
  const service = state.ai_stack?.services?.[route.service_id];
  $('#route-health').hidden = mode === 'photo';
  $('#route-health').classList.toggle('healthy', service?.runtime_enabled === true);
}
$$('[data-mode]').forEach(button => button.addEventListener('click', () => selectMode(button.dataset.mode)));

function appendUserMessage(prompt) {
  $('.welcome-card')?.remove();
  const item = document.createElement('div');
  item.className = 'message user';
  item.innerHTML = `<div class="bubble">${esc(prompt)}</div>`;
  $('#conversation').append(item);
  $('#conversation').scrollTop = $('#conversation').scrollHeight;
}
function appendThinking(label = 'ORCA is working') {
  const item = document.createElement('div');
  item.className = 'message assistant';
  item.id = 'active-thinking';
  item.innerHTML = `<div class="bubble thinking"><span class="welcome-orb small">O</span><span>${esc(label)}</span><span class="thinking-dots"><i></i><i></i><i></i></span></div>`;
  $('#conversation').append(item);
  $('#conversation').scrollTop = $('#conversation').scrollHeight;
}
function appendAssistant(result, route, error = false, sourcePrompt = '') {
  $('#active-thinking')?.remove();
  const item = document.createElement('div');
  item.className = 'message assistant';
  if (error) {
    item.innerHTML = `<div class="bubble"><p>${esc(result)}</p></div>`;
  } else {
    item.innerHTML = `<div class="bubble"><p>${esc(result.summary)}</p></div>`;
  }
  if (!error && /\b(photo|picture|image|illustration|draw)\b/i.test(sourcePrompt)) {
    const generate = document.createElement('button');
    generate.type = 'button'; generate.className = 'chat-image-download';
    generate.textContent = 'Generate image from this prompt';
    generate.addEventListener('click', () => runPrompt(sourcePrompt, 'photo'));
    item.querySelector('.bubble').append(generate);
  }
  $('#conversation').append(item);
  $('#conversation').scrollTop = $('#conversation').scrollHeight;
}

const chatImageURLs = new Set();
function wantsChatImage(prompt, mode) {
  if (mode === 'photo' || /^\/image\s+\S/i.test(prompt.trim())) return true;
  let text = prompt.trim().toLowerCase();
  if (/\b(?:don't|do not|never)\s+(?:generate|create|make|render|draw)\b/.test(text)) return false;
  if (/\b(?:photo|image|picture)\s+(?:editor|generator|generation|app|application|tool|api|button|feature|website)\b/.test(text)) return false;
  // Explicit image requests work in Chat and Visual as well as other rooms.
  // Conversational prefixes must not turn explanations or negations into jobs.
  text = text.replace(/^(?:(?:hey[ ,]+)?orca[,:]?\s+)?(?:(?:please|can you|could you|would you|will you)\s+)*/, '');
  text = text.replace(/^(?:i\s+(?:want|need|would like)|i'd like)\s+(?:you to\s+)?/, '');
  text = text.replace(/^please\s+/, '');
  if (/^(?:draw|paint)\s+(?:me\s+)?(?:a|an)\s+/.test(text)) return true;
  const requested = /^(?:(?:generate|create|make|render)\s+(?:me\s+)?)?(?:a|an|some)\s+[^.!?\n]{0,70}\b(?:photo|photograph|picture|image|illustration)s?\b/.test(text);
  const direct = /^(?:generate|create|make|render)\s+(?:me\s+)?(?:photo|photograph|picture|image|illustration)s?\b/.test(text);
  return (requested || direct) && !/^(?:how|why|explain|describe|write|can i)\b/.test(text);
}
function wantsChatVideo(prompt, mode) {
  if (mode === 'video' || /^\/video\s+\S/i.test(prompt.trim())) return true;
  let text = prompt.trim().toLowerCase();
  if (/\b(?:don't|do not|never)\s+(?:generate|create|make|render)\b/.test(text)) return false;
  if (/\bvideo\s+(?:editor|generator|generation|app|application|tool|api|button|feature|website)\b/.test(text)) return false;
  text = text.replace(/^(?:(?:hey[ ,]+)?orca[,:]?\s+)?(?:(?:please|can you|could you|would you|will you)\s+)*/, '');
  text = text.replace(/^(?:i\s+(?:want|need|would like)|i'd like)\s+(?:you to\s+)?/, '');
  text = text.replace(/^please\s+/, '');
  return /^(?:generate|create|make|render|produce)\s+(?:me\s+)?(?:a\s+)?(?:short\s+)?(?:video|clip|animation)\b/.test(text);
}
async function generateChatImage(prompt) {
  const imagePrompt = prompt.trim().replace(/^\/image\s+/i, '');
  if (!imagePrompt || imagePrompt.length > 1500) throw Error('Please use an image description of 1–1,500 characters.');
  const response = await fetch('/api/images/generate', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({prompt: imagePrompt, width: 1024, height: 1024, steps: 28})
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).error; } catch {}
    throw Error(detail || `Image generation failed (${response.status})`);
  }
  const blob = await response.blob();
  if (blob.type.split(';')[0] !== 'image/png') throw Error('The image service returned an unreadable image.');
  const url = URL.createObjectURL(blob);
  chatImageURLs.add(url);
  $('#active-thinking')?.remove();
  const item = document.createElement('div');
  item.className = 'message assistant';
  const bubble = document.createElement('div');
  bubble.className = 'bubble chat-image-result';
  const heading = document.createElement('h3');
  heading.textContent = 'Generated on CRUCIBLE';
  const image = document.createElement('img');
  image.src = url; image.alt = imagePrompt; image.className = 'chat-generated-image';
  const download = document.createElement('a');
  download.href = url; download.download = `ORCA-photo-${Date.now()}.png`;
  download.textContent = 'Save PNG'; download.className = 'chat-image-download';
  const edit = document.createElement('button');
  edit.type = 'button'; edit.textContent = 'Edit in Canvas'; edit.className = 'chat-image-download';
  edit.addEventListener('click', async () => {
    show('canvas');
    await showCanvasImage(url);
    canvasDescription = imagePrompt;
    $('#visual-prompt').value = imagePrompt;
    $('#visual-result').textContent = 'Loaded from chat. Describe the change, then edit the whole image or a selected area.';
  });
  const note = document.createElement('p');
  const size = response.headers.get('X-ORCA-Image-Size') || '1024x1024';
  const seed = response.headers.get('X-ORCA-Image-Seed') || 'recorded by broker';
  note.textContent = `${size.replace('x', ' × ')} · seed ${seed} · ${response.headers.get('X-ORCA-Image-Steps') || 28} steps · Save before refreshing.`;
  bubble.append(heading, image, download, edit, note); item.append(bubble);
  $('#conversation').append(item);
  image.addEventListener('load', () => { $('#conversation').scrollTop = $('#conversation').scrollHeight; });
  return `Generated a new image on CRUCIBLE from this description: ${imagePrompt}. The image was displayed in chat. Only its description is retained in memory, not its pixels.`;
}

async function generateChatVideo(prompt) {
  const videoPrompt = prompt.trim().replace(/^\/video\s+/i, '');
  if (!videoPrompt || videoPrompt.length > 1500) throw Error('Please use a video description of 1–1,500 characters.');
  const response = await fetch('/api/videos/generate', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({prompt: videoPrompt, width: 832, height: 480,
      length: 73, fps: 24, steps: 20})
  });
  if (!response.ok) {
    let detail; try { detail = (await response.json()).error; } catch {}
    throw Error(detail || `Video generation failed (${response.status})`);
  }
  const blob = await response.blob();
  if (blob.type.split(';')[0] !== 'video/mp4') throw Error('The video service returned an unreadable clip.');
  const url = URL.createObjectURL(blob); chatImageURLs.add(url);
  $('#active-thinking')?.remove();
  const item = document.createElement('div'); item.className = 'message assistant';
  const bubble = document.createElement('div'); bubble.className = 'bubble chat-image-result';
  const heading = document.createElement('h3'); heading.textContent = 'Generated on CRUCIBLE';
  const video = document.createElement('video');
  video.src = url; video.controls = true; video.loop = true; video.playsInline = true;
  const download = document.createElement('a');
  download.href = url; download.download = `ORCA-video-${Date.now()}.mp4`;
  download.textContent = 'Save MP4'; download.className = 'chat-image-download';
  const note = document.createElement('p');
  const frames = response.headers.get('X-ORCA-Video-Frames') || 73;
  const fps = response.headers.get('X-ORCA-Video-FPS') || 24;
  note.textContent = `${frames} frames · ${fps} fps · seed ${response.headers.get('X-ORCA-Image-Seed') || 'recorded by broker'} · Save before refreshing.`;
  bubble.append(heading, video, download, note); item.append(bubble);
  $('#conversation').append(item); $('#conversation').scrollTop = $('#conversation').scrollHeight;
  return `Generated a local MP4 on CRUCIBLE from this description: ${videoPrompt}. Only the description and generation record are retained in chat memory, not the video bytes.`;
}

async function runPrompt(prompt, mode = activeMode) {
  if (inferencePending || !prompt.trim()) return;
  inferencePending = true;
  $('#send-prompt').disabled = true;
  const videoRequest = wantsChatVideo(prompt, mode);
  const imageRequest = !videoRequest && mode !== 'auto' && wantsChatImage(prompt, mode);
  let route = routes[videoRequest ? 'video' : imageRequest ? 'photo' : mode];
  const history = boundedHistory(conversationHistory);
  const businessWorkflow = globalThis.ORCABusinessWorkflow?.take?.(prompt.trim()) || null;
  let businessJob = null;
  appendUserMessage(prompt.trim());
  appendThinking(videoRequest ? 'CRUCIBLE is generating your video…' : imageRequest ? 'CRUCIBLE is generating your image…' : 'ORCA is working');
  try {
    if (businessWorkflow) businessJob = await startBusinessWorkflow(businessWorkflow);
    const project = StudioLauncher.parseProject(prompt);
    if (project) {
      const plan = await postProjectPlan(project.prompt);
      const outcome = await StudioLauncher.createProject(plan);
      if (!outcome.ok) throw Error(outcome.message);
      const summary = projectSummary(plan, outcome);
      appendAssistant({summary}, routes.engineer, false, prompt.trim());
      await rememberConversation(prompt.trim(), summary);
      return;
    }
    const launch = StudioLauncher.parse(prompt);
    if (launch) {
      let message;
      if (launch.kind === 'view') {
        show(launch.target);
        message = `Opened ${launch.label}.`;
      } else if (launch.kind === 'operations') {
        showOps(launch.target);
        message = `Opened ${launch.label}.`;
      } else if (launch.kind === 'error') message = launch.label;
      else {
        const outcome = await StudioLauncher.launch(launch);
        message = outcome.message;
        if (!outcome.ok && launch.url) {
          appendAssistant({summary: message}, routes.reason);
          const link = document.createElement('a');
          link.href = launch.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
          link.textContent = `Open ${launch.label} in your browser`;
          $('#conversation').lastElementChild.querySelector('.bubble').append(link);
          return;
        }
      }
      appendAssistant({summary: message}, routes.reason);
      // Launch URLs may contain private query parameters; do not archive them.
      return;
    }
    let result, imagePrompt = imageRequest ? prompt : null;
    let videoPrompt = videoRequest ? prompt : null;
    if (mode === 'auto' && !videoRequest) {
      const chosen = await postChat(prompt.trim(), history, businessJob?.id || null);
      if (!routes[chosen.mode] || chosen.mode === 'auto') throw Error('Studio returned an unknown capability.');
      route = routes[chosen.mode];
      imagePrompt = chosen.mode === 'photo' ? chosen.image_prompt : null;
      result = chosen.result;
      if (imagePrompt) {
        $('#active-thinking')?.remove(); appendThinking('CRUCIBLE is generating your image…');
      }
    } else if (!imageRequest && !videoRequest) result = await postInference(prompt.trim(), mode, history);
    if (videoPrompt) {
      const memory = await generateChatVideo(videoPrompt);
      await rememberConversation(prompt.trim(), memory);
    } else if (imagePrompt) {
      const memory = await generateChatImage(imagePrompt);
      await rememberConversation(prompt.trim(), memory);
    } else {
      appendAssistant(result, route, false, prompt.trim());
      await rememberConversation(prompt.trim(), result.summary);
    }
  }
  catch (error) { appendAssistant(error.message, route, true); }
  finally {
    inferencePending = false; $('#send-prompt').disabled = false;
    if (businessJob) await refresh();
  }
}

$('#prompt-form').addEventListener('submit', async event => {
  event.preventDefault();
  const prompt = $('#prompt-input').value;
  if (inferencePending || !prompt.trim()) return;
  $('#prompt-input').value = '';
  await runPrompt(prompt);
});
$('#prompt-input').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (!event.repeat && !inferencePending) $('#prompt-form').requestSubmit();
  }
});
document.addEventListener('click', async event => {
  const button = event.target.closest?.('[data-launch-app]');
  if (!button || button.disabled) return;
  const status = button.closest('#business') ? $('#business-app-status') : $('#engineering-app-status');
  button.disabled = true;
  if (status) status.textContent = `Opening ${button.querySelector('strong')?.textContent || 'application'} on KILN…`;
  try {
    const result = await StudioLauncher.launch({kind:'app', target:button.dataset.launchApp});
    if (status) status.textContent = result.message;
  } finally { button.disabled = false; }
});
$$('[data-starter]').forEach(button => button.addEventListener('click', () => {
  $('#prompt-input').value = button.dataset.starter;
  $('#prompt-input').focus();
}));
$$('[data-code-prompt]').forEach(button => button.addEventListener('click', () => {
  show('studio'); selectMode('code'); $('#prompt-input').value = 'Implement and test '; $('#prompt-input').focus();
}));
$$('[data-engineering-prompt]').forEach(button => button.addEventListener('click', () => {
  show('studio'); selectMode('engineer'); $('#prompt-input').value = 'Engineer and verify '; $('#prompt-input').focus();
}));
$('#new-thread').addEventListener('click', () => {
  if (inferencePending) return;
  globalThis.ORCABusinessWorkflow?.clear?.();
  for (const url of chatImageURLs) URL.revokeObjectURL(url);
  chatImageURLs.clear();
  conversationHistory = [];
  try { localStorage.removeItem(chatMemoryKey); } catch {}
  selectMode('auto');
  $('#conversation').innerHTML = `<div class="welcome-card"><span class="welcome-orb">O</span><h2>New room</h2><p>Describe the outcome. Auto chooses the capability for you.</p></div>`;
  show('studio'); $('#prompt-input').focus();
});

try {
  const saved = JSON.parse(localStorage.getItem(chatMemoryKey) || '[]');
  conversationHistory = boundedHistory(Array.isArray(saved) ? saved : []);
} catch { conversationHistory = []; }
if (conversationHistory.length) {
  $('.welcome-card')?.remove();
  for (const message of conversationHistory) {
    if (message.role === 'user') appendUserMessage(message.content);
    else {
      const item = document.createElement('div'); item.className = 'message assistant';
      const bubble = document.createElement('div'); bubble.className = 'bubble';
      const text = document.createElement('p'); text.textContent = message.content.split('\nEvidence: ')[0];
      bubble.append(text); item.append(bubble); $('#conversation').append(item);
    }
  }
}

function setAuth(identity, token, native = false) {
  studioAuth = { identity, token };
  $('#operator-identity').value = identity;
  $('#operator-token').value = token;
  if (token && !native) {
    window.webkit?.messageHandlers?.orcaCredential?.postMessage({ identity, token });
  }
}
window.orcaReceiveDesktopAuth = auth => {
  if (auth?.identity && auth?.token) setAuth(auth.identity, auth.token, true);
};
if (window.ORCA_DESKTOP_AUTH?.token) setAuth(
  window.ORCA_DESKTOP_AUTH.identity || 'fry', window.ORCA_DESKTOP_AUTH.token, true
);

function jobRow(job) {
  return `<div class="row"><div class="row-top"><h3>${esc(job.title)} <span class="badge ${esc(job.level)}">${esc(job.level)}</span></h3><span class="state ${esc(job.status)}">${esc(job.status)}</span></div><p>${esc(job.action?.kind)} · ${esc(job.action?.resource)}</p><div class="meta">${esc(job.lane)} / ${esc(job.assigned_to)}${job.target_node ? ` → ${esc(job.target_node.toUpperCase())}` : ''} · route ${esc(job.model_route || 'manual')} · stop ${esc(job.stop_condition || 'independent_review_complete')} · ${esc(job.correlation_id)}</div></div>`;
}
function eventRow(event) {
  return `<div class="row"><div class="row-top"><h3>${esc(event.kind)}</h3><span class="state">${esc(event.actor)}</span></div><p>${esc(event.lane)} · ${esc(event.correlation_id)}</p><div class="meta">${esc(event.timestamp)}</div></div>`;
}
function render() {
  const pending = state.approvals.filter(approval => approval.status === 'pending');
  $('#approval-banner').classList.toggle('hidden', !pending.length);
  $('#approval-count').textContent = `${pending.length} approval${pending.length === 1 ? '' : 's'} waiting`;
  $('#active-jobs').textContent = state.jobs.filter(job => !['complete', 'failed', 'denied'].includes(job.status)).length;
  $('#waiting-jobs').textContent = pending.length;
  $('#chain-state').textContent = state.evidence_chain_valid ? 'VALID' : 'FAILED';
  $('#chain-state').style.color = state.evidence_chain_valid ? 'var(--mint)' : 'var(--red)';
  $('#paused-lanes').textContent = state.paused_lanes.length;
  $('#system-status').textContent = state.evidence_chain_valid ? 'Fabric healthy' : 'Integrity failure';
  const healthy = state.nodes.filter(node => node.state === 'healthy' && !node.paused);
  $('#fleet-mini-status').textContent = `${healthy.length} nodes healthy`;
  $('#fleet-mini-detail').textContent = state.ai_stack?.model_invocation_enabled ? 'Local AI active' : 'Models gated';
  const jobs = state.jobs.map(jobRow).join('') || '<div class="stack empty">No work submitted.</div>';
  $('#job-list').innerHTML = jobs;
  $('#overview-job-list').innerHTML = jobs;
  const events = state.events.slice(0, 30).map(eventRow).join('') || '<div class="stack empty">No evidence recorded.</div>';
  $('#event-list').innerHTML = events;
  $('#evidence-list').innerHTML = events;
  $('#fabric-summary').innerHTML = state.nodes.filter(node => node.id !== 'temper').map(node => `<div class="fabric-node"><span><i style="background:${node.state === 'healthy' && !node.paused ? 'var(--mint)' : 'var(--amber)'}"></i>${esc(node.name)}</span><span>${node.paused ? 'paused' : esc(node.state)}</span></div>`).join('');
  renderSafety(); renderSecurity(); renderAgents(); renderConnectors(); renderGovernance(); renderCosts(); renderActions(); renderCoderStack(); renderBusinessMetrics();
  renderInventoryWorkflows();
  if (typeof renderFabricTelemetry === 'function') renderFabricTelemetry(state.nodes);
  selectMode(activeMode);
  syncMutationControls();
}

function renderBusinessMetrics() {
  const jobs = state.jobs.filter(job => job.task_type === 'business_workflow');
  const active = jobs.filter(job => !['complete', 'failed', 'denied'].includes(job.status));
  const jobIDs = new Set(jobs.map(job => job.id));
  const approvals = state.approvals.filter(item => item.status === 'pending' && jobIDs.has(item.job_id));
  const records = Object.values(state.business?.counts || {})
    .reduce((total, count) => total + Number(count || 0), 0);
  const activeNode = $('#business-active-count');
  const approvalNode = $('#business-approval-count');
  const recordNode = $('#business-record-count');
  if (activeNode) activeNode.textContent = active.length;
  if (approvalNode) approvalNode.textContent = approvals.length;
  if (recordNode) recordNode.textContent = records;
}

function renderSafety() {
  const stop = $('#stop-state');
  stop.textContent = state.emergency_stop ? 'EMERGENCY STOP' : 'NORMAL';
  stop.style.color = state.emergency_stop ? 'var(--red)' : 'var(--mint)';
  $('#incident-list').innerHTML = state.incidents.map(incident => `<div class="row"><div class="row-top"><h3>${esc(incident.title)} <span class="badge ${incident.severity === 'S0' ? 'R0' : incident.severity === 'S1' ? 'R1' : incident.severity === 'S2' ? 'R2' : 'R3'}">${esc(incident.severity)}</span></h3><span class="state">${esc(incident.status)}</span></div><p>${esc(incident.detail)}</p><div class="meta">${esc(incident.lane)} · ${esc(incident.owner)} · ${esc(incident.correlation_id)}</div></div>`).join('') || '<div class="stack empty">No incidents recorded.</div>';
}
function renderSecurity() {
  const reports = [...(state.security_reports || [])].reverse();
  $('#security-list').innerHTML = reports.map(report => {
    const findings = (report.findings || []).map(finding => `<div class="row"><div class="row-top"><strong>${esc(finding.summary)}</strong><span class="badge ${finding.severity === 'S1' ? 'R1' : finding.severity === 'S2' ? 'R2' : 'R3'}">${esc(finding.severity)}</span></div><p>${esc(finding.evidence)}</p><div class="meta">${esc(finding.artifact)} · ${esc(finding.check_id)}</div><p>${esc(finding.remediation)}</p></div>`).join('') || '<p class="muted">No findings.</p>';
    return `<div class="row"><div class="row-top"><h3>${esc(report.id)}</h3><span class="state ${report.disposition === 'pass' ? 'complete' : 'waiting_approval'}">${esc(report.disposition)}</span></div><div class="meta">${esc(report.lane)} · author ${esc(report.author)} · ${esc(report.engine)}</div>${findings}</div>`;
  }).join('') || '<div class="stack empty">No security reports recorded.</div>';
}
function renderAgents() {
  const terminal=['complete','failed','denied'];
  $('#agent-grid').innerHTML=state.agents.map(agent=>{const bot=(state.bots||[]).find(item=>item.id===agent.id),assignments=state.jobs.filter(job=>(job.assigned_to===agent.id||job.reviewer===agent.id)&&!terminal.includes(job.status)),incidents=state.incidents.filter(incident=>incident.owner===agent.id&&incident.status!=='closed'),tools=state.tool_manifests?.[agent.id]||[];return `<article><div class="row-top"><h2 class="agent-name">${esc(agent.name)}</h2><span class="state ${bot?.paused?'failed':'complete'}">${bot?.paused?'PAUSED':agent.enabled?'ENABLED':'DISABLED'}</span></div><p class="role">${esc(agent.duty)}</p><div class="meta">${assignments.length} active assignments · ${incidents.length} open incidents${bot?' · '+esc(bot.model_route)+' route':''}</div><div class="flags"><span class="flag">${tools.length?tools.length+' TOOLS':'NO TOOLS'}</span>${bot?`<span class="flag">${bot.runtime_enabled?'RUNTIME ENABLED':'RUNTIME DISABLED'}</span>`:''}${agent.may_author?'<span class="flag">AUTHOR</span>':''}${agent.may_review?'<span class="flag">REVIEW</span>':''}${agent.may_deploy?'<span class="flag">DEPLOY</span>':''}</div></article>`}).join('');
  $('#fleet-grid').innerHTML = state.nodes.map(node => `<article><div class="row-top"><h2 class="agent-name">${esc(node.name)}</h2><span class="state ${esc(node.state)}">${node.paused ? 'PAUSED' : esc(node.state)}</span></div><p class="role">${esc(node.duty)}</p><div class="meta">${esc(node.kind)} · ${esc(node.address)} · ${esc(node.lane)}</div><div class="flags"><span class="flag">${esc(node.permission_floor)} FLOOR</span><span class="flag">${node.remote_execution_enabled ? 'REMOTE ENABLED' : 'REMOTE DISABLED'}</span></div></article>`).join('');
}
function renderConnectors() {
  const capabilities = state.connector_capabilities || [];
  $('#connector-grid').innerHTML = state.connectors.map(connector => { const cap = capabilities.find(item => item.connector === connector.id), actions = cap?.declared_actions || [], levels = [...new Set(actions.map(action => action.level))].sort().join(' / '); return `<article><h2 class="connector-name">${esc(connector.name)}</h2><p class="role">${esc(connector.authority)}</p><div class="flags"><span class="flag">${levels ? esc(levels) + ' DECLARED' : 'UNMAPPED'}</span><span class="flag">${connector.writes_enabled ? 'WRITE ENABLED' : 'WRITE DISABLED'}</span></div><div class="meta">${actions.length} classified actions</div></article>`; }).join('');
}
function renderGovernance() {
  const audits = state.retention_audits || [], latest = audits[audits.length - 1], policy = state.governance?.retention_enforcement || {};
  $('#retention-summary').innerHTML = `<div class="row"><div class="row-top"><h3>${esc(policy.mode || 'deny-by-default')}</h3><span class="state">${policy.automatic_deletion ? 'AUTO DELETE' : 'DRY RUN ONLY'}</span></div><p>Evidence deletion: ${policy.evidence_deletion ? 'enabled' : 'prohibited'} · expired records require ${esc(policy.expired_records_require || 'Fry R3 review')}</p></div>` + (latest ? `<div class="row"><h3>${esc(latest.id)}</h3><p>${latest.record_count} records · ${latest.automatic_deletions} deletions</p></div>` : '');
}
function renderCosts() {
  const costs = state.costs || { total_usd: 0, hard_cap_usd: 0, by_dimension: {} };
  $('#cost-total').innerHTML = `$${Number(costs.total_usd).toFixed(2)} <small>recorded usage · $${Number(costs.hard_cap_usd).toFixed(2)} hard cap</small>`;
  $('#budget-policy').textContent = `Policy: ${costs.budget_status || 'zero_spend'} · paid execution ${costs.paid_execution_authorized ? 'authorized' : 'not authorized'}`;
  $('#cost-breakdown').innerHTML = (costs.by_dimension?.bot_id || []).map(item => `<div class="row"><div class="row-top"><h3>${esc(item.key)}</h3><span class="state">$${Number(item.cost_usd).toFixed(4)}</span></div><p>${item.tokens_in} in · ${item.tokens_out} out</p></div>`).join('') || '<div class="stack empty">No usage recorded.</div>';
}
function renderActions() {
  const pending=state.approvals.filter(approval=>approval.status==='pending');
  $('#approval-list').innerHTML=pending.map(approval=>{const job=state.jobs.find(item=>item.id===approval.job_id)||{},rollback=job.action?.rollback||'none declared',rationale=(approval.rationale||[]).join(' · ');return `<div class="row"><div class="row-top"><h3>${esc(job.title)} <span class="badge R${approval.level}">R${approval.level}</span></h3><span class="state waiting_approval">BLOCKED</span></div><p>${esc(job.action?.kind)} · ${esc(job.action?.resource)}</p><div class="meta">Why: ${esc(rationale||'policy classification')} · rollback: ${esc(rollback)}</div><div class="flags"><button data-approval="${esc(approval.id)}" data-decision="approve">Approve</button><button data-approval="${esc(approval.id)}" data-decision="deny">Deny</button></div></div>`}).join('')||'<div class="stack empty">No approvals waiting.</div>';
  $('#work-list').innerHTML=state.jobs.map(job=>{const actions=[];if(job.status==='paused')actions.push(`<button data-job-action="resume" data-job-id="${esc(job.id)}">Resume</button>`);if(job.status==='ready')actions.push(`<button data-job-action="start" data-job-id="${esc(job.id)}">Start</button>`);if(job.status==='running')actions.push(`<button data-job-action="review" data-job-id="${esc(job.id)}">Request review</button>`);if(job.status==='review')actions.push(`<button data-job-action="complete" data-job-id="${esc(job.id)}">Complete review</button>`);if(!['complete','failed','denied','paused'].includes(job.status))actions.push(`<button data-pause-job="${esc(job.id)}">Pause</button>`);return jobRow(job).replace('</div></div>',`</div><div class="flags">${actions.join('')}</div></div>`)}).join('')||'<div class="stack empty">No work submitted.</div>';
}
function renderCoderStack() {
  const services = state.ai_stack?.services || {};
  const ids = ['kiln_codex', 'forge_qwen', 'kiln_quench'];
  $('#coder-stack').innerHTML = ids.map(id => { const service = services[id] || {}; return `<div class="specialist-row"><div><strong>${esc(id === 'kiln_codex' ? 'Codex on KILN' : id === 'forge_qwen' ? 'Qwen Local Fallback' : 'QUENCH')}</strong><div class="meta">${esc(service.model || 'loading')}</div></div><span class="state ${service.runtime_enabled ? 'complete' : 'failed'}">${service.runtime_enabled ? 'READY' : 'GATED'}</span></div>`; }).join('');
}

async function refresh() {
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (!response.ok) throw Error(response.status);
    state = await response.json();
    render();
  } catch {
    $('#system-status').textContent = 'Control plane offline';
    $$('.pulse').forEach(pulse => { pulse.style.background = 'var(--red)'; });
  }
}

async function loadInventory(force = false) {
  if (inventoryAnalysis && !force) { renderInventory(); return; }
  $('#inventory-source').textContent = 'Reading KILN canonical bench inventory…';
  try {
    const [response, systemResponse] = await Promise.all([
      fetch('/api/inventory/analysis', { cache: 'no-store' }),
      fetch('/api/inventory/system', { cache: 'no-store' })
    ]);
    const body = await response.json();
    if (!response.ok) throw Error(body.error || response.status);
    inventory = body.snapshot;
    inventoryAnalysis = body.analysis;
    if (systemResponse.ok) inventorySystem = await systemResponse.json();
    $('#inventory-source').textContent = `${body.analysis.source} · analyzed ${body.analysis.generated_at} · no stock changes`;
    const category = $('#inventory-category'), location = $('#inventory-location');
    const selectedCategory = category.value, selectedLocation = location.value;
    category.innerHTML = '<option value="">All categories</option>' + body.analysis.categories.map(item => `<option value="${esc(item.name)}">${esc(item.name)}</option>`).join('');
    location.innerHTML = '<option value="">All locations</option>' + body.analysis.locations.map(item => `<option value="${esc(item.name)}">${esc(item.name)}</option>`).join('');
    category.value = selectedCategory; location.value = selectedLocation;
    renderInventory();
    renderInventorySystem();
  } catch (error) {
    $('#inventory-source').textContent = `Inventory unavailable: ${error.message}`;
    $('#inventory-rows').innerHTML = '<tr><td colspan="10">The canonical inventory could not be reached.</td></tr>';
    $('#inventory-alerts').innerHTML = '<p>Analysis is unavailable until the canonical source can be read.</p>';
  }
}
function renderInventorySystem() {
  const grid = $('#inventory-system-grid'), status = $('#inventory-system-status');
  if (!grid || !status || !inventorySystem) return;
  grid.innerHTML = inventorySystem.modules.map(module => `<article><span>${esc(module.mode === 'agentic_with_approval' ? 'AGENTIC' : module.mode)}</span><strong>${esc(module.name)}</strong><small>${esc(module.purpose)}</small><button type="button" data-inventory-module="${esc(module.name)}">Open workflow</button></article>`).join('');
  status.textContent = `${inventorySystem.module_count} implemented modules · ${inventorySystem.agent_loop.join(' → ')} · approval boundaries enforced`;
}
document.addEventListener('click', event => {
  const button = event.target.closest('[data-inventory-module]');
  if (!button) return;
  showView('chat');
  const input = $('#chat-input');
  input.value = `Run the ${button.dataset.inventoryModule} inventory workflow agentically. Inspect verified records first; reconcile conflicts; plan and simulate; show evidence, assumptions, files and systems used; then stop for my approval before money, stock changes, external messages, publishing, write-offs, recalls, or external writes.`;
  input.focus();
});
function renderInventory() {
  if (!inventoryAnalysis) return;
  const query = $('#inventory-search').value.trim().toLowerCase();
  const category = $('#inventory-category').value, location = $('#inventory-location').value, stateFilter = $('#inventory-state').value;
  const rows = inventoryAnalysis.items.filter(item => (!query || [item.name, item.sku, item.category, item.location, item.lot, item.serial].some(value => String(value || '').toLowerCase().includes(query))) && (!category || item.category === category) && (!location || item.location === location) && (!stateFilter || item.status === stateFilter));
  const metrics = inventoryAnalysis.metrics;
  const fmt = value => Number(value || 0).toLocaleString(undefined, {maximumFractionDigits: 2});
  $('#inventory-metrics').innerHTML = `<article><span>Cataloged records</span><strong>${fmt(metrics.records)}</strong><small>${fmt(metrics.unique_skus)} identified SKUs</small></article><article><span>Available units</span><strong>${fmt(metrics.available)}</strong><small>${fmt(metrics.reserved)} reserved</small></article><article><span>Needs attention</span><strong>${fmt(metrics.attention)}</strong><small>${fmt(metrics.stockouts)} stockouts · ${fmt(metrics.reorder)} reorder</small></article><article><span>Count freshness</span><strong>${fmt(metrics.records - metrics.stale)}/${fmt(metrics.records)}</strong><small>${fmt(metrics.stale)} stale or undated</small></article><article><span>Traceability</span><strong>${fmt(metrics.traceable)}/${fmt(metrics.records)}</strong><small>lot or serial evidence</small></article><article><span>Recorded value</span><strong>$${fmt(metrics.inventory_value)}</strong><small>${fmt(metrics.valued_records)}/${fmt(metrics.records)} records valued</small></article>`;
  const actionable = inventoryAnalysis.exceptions.slice(0, 12);
  $('#inventory-alerts').innerHTML = actionable.map(item => `<div class="inventory-alert ${esc(item.severity)}"><span>${esc(item.severity)}</span><div><strong>${esc(item.item)} · ${esc(item.type.replaceAll('_', ' '))}</strong><small>${esc(item.detail)}</small></div></div>`).join('') || '<p class="stock-ok">No inventory exceptions detected.</p>';
  $('#inventory-locations').innerHTML = inventoryAnalysis.locations.map(item => `<div><span><strong>${esc(item.name)}</strong><small>${fmt(item.items)} records · ${fmt(item.available)} available</small></span><b class="${item.needs_attention ? 'stock-low' : 'stock-ok'}">${fmt(item.needs_attention)} flagged</b></div>`).join('') || '<p>No locations recorded.</p>';
  const duplicateCount = inventoryAnalysis.exceptions.filter(item => item.type === 'duplicate_sku').length;
  const missingSku = inventoryAnalysis.exceptions.filter(item => item.type === 'missing_sku').length;
  const overReserved = inventoryAnalysis.exceptions.filter(item => item.type === 'over_reserved').length;
  $('#inventory-quality').innerHTML = `<div><span>Duplicate SKU records</span><strong class="${duplicateCount ? 'stock-low' : 'stock-ok'}">${fmt(duplicateCount)}</strong></div><div><span>Missing SKU</span><strong class="${missingSku ? 'stock-low' : 'stock-ok'}">${fmt(missingSku)}</strong></div><div><span>Over-reserved</span><strong class="${overReserved ? 'stock-low' : 'stock-ok'}">${fmt(overReserved)}</strong></div><div><span>Control mode</span><strong>Read-only</strong></div>`;
  $('#inventory-result-count').textContent = `${rows.length} of ${inventoryAnalysis.items.length} records shown`;
  $('#inventory-rows').innerHTML = rows.map(item => `<tr><td>${esc(item.sku || '—')}</td><td>${esc(item.name)}</td><td>${esc(item.category)}</td><td>${fmt(item.on_hand)} ${esc(item.unit)}</td><td>${fmt(item.reserved)}</td><td>${fmt(item.available)}</td><td>${item.reorder_quantity == null ? (item.reorder_point == null ? 'Not set' : 'Review qty') : fmt(item.reorder_quantity)}</td><td>${esc(item.location)}</td><td class="${item.status === 'healthy' ? 'stock-ok' : 'stock-low'}">${esc(item.status)}</td><td>${esc(item.last_updated || 'Unknown')}</td></tr>`).join('') || '<tr><td colspan="10">No inventory matches those filters.</td></tr>';
}
function renderInventoryWorkflows() {
  const target = $('#inventory-workflow-jobs');
  if (!target) return;
  const jobs = (state.jobs || []).filter(job => ['inventory_workflow', 'inventory_count_session'].includes(job.task_type)).slice(-8).reverse();
  target.innerHTML = jobs.map(job => {
    const operation = job.action?.metadata?.operation || {}, preview = job.action?.metadata?.preview || {};
    const session = job.action?.metadata?.count_session;
    const after = session ? `${session.metrics.observations} observations · ${session.metrics.variances} variances · net ${session.metrics.net_variance}` : Object.entries(preview).map(([location, row]) => `${esc(location)}: ${Number(row.on_hand).toLocaleString()} on hand, ${Number(row.reserved).toLocaleString()} reserved`).join(' · ');
    const endpoint = session ? 'counts' : 'workflows';
    const execute = job.status === 'ready' ? `<button type="button" data-inventory-execute="${esc(job.id)}" data-inventory-endpoint="${endpoint}">Execute approved change</button>` : '';
    return `<div class="inventory-workflow-job"><div><strong>${esc(session ? 'physical count session' : operation.operation_type?.replaceAll('_', ' ') || job.title)} · ${esc(operation.sku || session?.session_id || '')}</strong><small>${esc(after || 'Preview unavailable')}</small><small>${esc(operation.reason || session?.reason || '')}</small></div><span class="state ${esc(job.status)}">${esc(job.status)}</span>${execute}</div>`;
  }).join('') || '<p class="muted">No inventory workflow proposals yet.</p>';
}
function syncInventoryWorkflowFields() {
  const kind = $('#inventory-operation').value;
  $('#inventory-target-label').hidden = kind !== 'transfer';
  $('#inventory-workflow-target').required = kind === 'transfer';
  $('#inventory-quantity-label').textContent = ['cycle_count', 'adjustment'].includes(kind) ? 'New on-hand quantity' : 'Quantity';
}
$('#inventory-operation').addEventListener('change', syncInventoryWorkflowFields);
syncInventoryWorkflowFields();
$('#inventory-workflow-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (mutationPending) return;
  const status = $('#inventory-workflow-status'), kind = $('#inventory-operation').value;
  const operation = {
    operation_type: kind,
    sku: $('#inventory-workflow-sku').value.trim(),
    location: $('#inventory-workflow-location').value.trim(),
    quantity: Number($('#inventory-workflow-quantity').value),
    reason: $('#inventory-workflow-reason').value.trim(),
    evidence: $('#inventory-workflow-evidence').value.trim()
  };
  if (kind === 'transfer') operation.target_location = $('#inventory-workflow-target').value.trim();
  status.textContent = 'Validating the baseline and calculating the before/after state…';
  try {
    const result = await postMutation('/api/inventory/workflows', {operation}, controlAuth());
    status.textContent = `Proposal ${result.job.id} created. Fry approval is required before ORCA can execute it.`;
    await refresh();
  } catch (error) { status.textContent = `Proposal failed: ${error.message}`; }
});
document.addEventListener('click', async event => {
  const button = event.target.closest('[data-inventory-execute]');
  if (!button || mutationPending) return;
  const status = $('#inventory-workflow-status');
  status.textContent = 'Executing the approved canonical stock change…';
  try {
    const endpoint = button.dataset.inventoryEndpoint || 'workflows';
    const result = await postMutation(`/api/inventory/${endpoint}/${button.dataset.inventoryExecute}/execute`, {confirm: true}, controlAuth());
    const label = result.operation?.operation_type?.replaceAll('_', ' ') || 'physical count session';
    status.textContent = `${label} applied to ORCA's canonical ledger and sent to QUENCH review. KILN source stock was not changed.`;
    await refresh();
  } catch (error) { status.textContent = `Execution failed: ${error.message}`; }
});
function renderInventoryCountRows() {
  $('#inventory-count-rows').innerHTML = inventoryCountRows.map((row, index) => `<tr><td>${esc(row.sku)}</td><td>${esc(row.location)}</td><td>${Number(row.counted_quantity).toLocaleString()} ${esc(row.unit)}</td><td>${esc([row.lot, row.serial].filter(Boolean).join(' / ') || '—')}</td><td>${esc(row.condition)}</td><td><button type="button" data-remove-count="${index}">Remove</button></td></tr>`).join('') || '<tr><td colspan="6">No observations entered.</td></tr>';
}
$('#inventory-count-row-form').addEventListener('submit', event => {
  event.preventDefault();
  const sku = $('#inventory-count-sku').value.trim(), serial = $('#inventory-count-serial').value.trim();
  const row = {sku, barcode: sku, location: $('#inventory-count-location').value.trim(), counted_quantity: Number($('#inventory-count-quantity').value), unit: $('#inventory-count-unit').value.trim() || 'ea', lot: $('#inventory-count-lot').value.trim(), serial, condition: $('#inventory-count-condition').value, notes: $('#inventory-count-notes').value.trim()};
  if (serial && row.counted_quantity !== 1) { $('#inventory-count-status').textContent = 'Serialized observations must count exactly one unit.'; return; }
  inventoryCountRows.push(row); renderInventoryCountRows();
  $('#inventory-count-sku').value = ''; $('#inventory-count-quantity').value = ''; $('#inventory-count-lot').value = ''; $('#inventory-count-serial').value = ''; $('#inventory-count-notes').value = '';
  $('#inventory-count-sku').focus();
  $('#inventory-count-status').textContent = `${inventoryCountRows.length} observation${inventoryCountRows.length === 1 ? '' : 's'} staged locally.`;
});
document.addEventListener('click', event => {
  const button = event.target.closest('[data-remove-count]');
  if (!button) return;
  inventoryCountRows.splice(Number(button.dataset.removeCount), 1); renderInventoryCountRows();
});
async function submitInventoryCount(previewOnly) {
  const status = $('#inventory-count-status');
  if (!inventoryCountRows.length) { status.textContent = 'Add at least one count observation.'; return; }
  const payload = {observations: inventoryCountRows, reason: $('#inventory-count-reason').value.trim(), evidence: $('#inventory-count-evidence').value.trim()};
  if (!payload.reason || !payload.evidence) { status.textContent = 'Count reason and evidence reference are required.'; return; }
  status.textContent = previewOnly ? 'Reconciling counts against the canonical ledger…' : 'Creating the governed batch count proposal…';
  try {
    const result = await postMutation(previewOnly ? '/api/inventory/counts/preview' : '/api/inventory/counts', payload, controlAuth());
    const session = result.session || result;
    $('#inventory-count-preview-result').innerHTML = `<div class="inventory-count-metrics"><span>${session.metrics.observations} observations</span><span>${session.metrics.matches} matches</span><span>${session.metrics.variances} variances</span><span>${session.metrics.blocked} blocked</span><span>Net ${session.metrics.net_variance}</span></div>` + session.rows.map(row => `<div class="inventory-count-result ${esc(row.status)}"><strong>${esc(row.sku)} · ${esc(row.location)}</strong><span>${Number(row.recorded_on_hand).toLocaleString()} recorded → ${Number(row.counted_quantity).toLocaleString()} counted · variance ${Number(row.variance).toLocaleString()}</span>${row.blocker ? `<small>${esc(row.blocker)}</small>` : ''}</div>`).join('');
    status.textContent = previewOnly ? `Review complete: ${session.metrics.variances} variances and ${session.metrics.blocked} blockers.` : `Count session ${session.session_id} is waiting for Fry approval.`;
    if (!previewOnly) { inventoryCountRows = []; renderInventoryCountRows(); await refresh(); }
  } catch (error) { status.textContent = `Count session failed: ${error.message}`; }
}
$('#inventory-count-preview').addEventListener('click', () => submitInventoryCount(true));
$('#inventory-count-submit').addEventListener('click', () => submitInventoryCount(false));
['#inventory-search', '#inventory-category', '#inventory-location', '#inventory-state'].forEach(selector => $(selector).addEventListener(selector === '#inventory-search' ? 'input' : 'change', renderInventory));
$('#refresh-inventory').addEventListener('click', () => loadInventory(true));

const canvas = $('#drawing-canvas');
const context = canvas.getContext('2d');
const maskCanvas = $('#mask-canvas'), maskContext = maskCanvas.getContext('2d');
let canvasBusy = false, canvasHasImage = false, maskPainted = false;
const canvasUndo = [];
let canvasDescription = '';
let generatedVideoURL = null;
function setCanvasBusy(busy) {
  canvasBusy = busy;
  $$('#canvas button,#canvas input,#canvas select,#canvas textarea').forEach(control => { control.disabled = busy; });
  $('#undo-canvas').disabled = busy || !canvasUndo.length;
}
function clearSelection() {
  maskContext.clearRect(0, 0, maskCanvas.width, maskCanvas.height); maskPainted = false;
}
function snapshotCanvas() {
  if (!canvasHasImage) return;
  canvasUndo.push({image: context.getImageData(0, 0, canvas.width, canvas.height), description: canvasDescription});
  if (canvasUndo.length > 5) canvasUndo.shift();
}
function decodeCanvasImage(source) {
  return new Promise((resolve, reject) => {
    const image = new Image(); image.onload = () => resolve(image);
    image.onerror = () => reject(Error('Could not open that image. Use PNG, JPEG or WebP.'));
    image.src = source;
  });
}
async function showCanvasImage(source, saveUndo = true) {
  const image = await decodeCanvasImage(source);
  if (image.naturalWidth * image.naturalHeight > 40_000_000) throw Error('Image is too large; resize it below 40 megapixels first.');
  const scale = Math.min(1, 1024 / Math.max(image.naturalWidth, image.naturalHeight));
  const width = Math.max(64, Math.round(image.naturalWidth * scale / 8) * 8);
  const height = Math.max(64, Math.round(image.naturalHeight * scale / 8) * 8);
  if (saveUndo) snapshotCanvas();
  canvas.width = maskCanvas.width = width; canvas.height = maskCanvas.height = height;
  context.fillStyle = '#ffffff'; context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);
  canvasHasImage = true; clearSelection();
  $('#undo-canvas').disabled = !canvasUndo.length;
}
for (const surface of [canvas, maskCanvas]) {
  let drawing = false;
  const ctx = surface.getContext('2d');
  const point = event => { const rect = surface.getBoundingClientRect(); return {
    x: (event.clientX - rect.left) * surface.width / rect.width,
    y: (event.clientY - rect.top) * surface.height / rect.height}; };
  surface.addEventListener('pointerdown', event => {
    if (canvasBusy) return;
    if (surface === maskCanvas && !canvasHasImage) { $('#visual-result').textContent = 'Upload or generate an image first.'; return; }
    if (surface === canvas) { snapshotCanvas(); canvasHasImage = true; }
    drawing = true; surface.setPointerCapture(event.pointerId);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = surface === maskCanvas ? '#ffffff' : $('#brush-color').value;
    ctx.lineWidth = Number($('#brush-size').value) * surface.width / surface.clientWidth;
    const p = point(event); ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + .01, p.y); ctx.stroke();
    if (surface === maskCanvas) maskPainted = true;
  });
  surface.addEventListener('pointermove', event => {
    if (!drawing || canvasBusy) return;
    const p = point(event); ctx.lineTo(p.x, p.y); ctx.stroke();
  });
  for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) surface.addEventListener(name, () => {
    drawing = false; $('#undo-canvas').disabled = canvasBusy || !canvasUndo.length;
  });
}
$('#canvas-tool').addEventListener('change', () => { maskCanvas.hidden = $('#canvas-tool').value !== 'mask'; });
$('#clear-mask').addEventListener('click', clearSelection);
$('#canvas-upload').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file || canvasBusy) return;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 20_000_000) {
    $('#visual-result').textContent = 'Choose a PNG, JPEG or WebP file under 20 MB.'; event.target.value = ''; return;
  }
  setCanvasBusy(true); const url = URL.createObjectURL(file);
  try {
    await showCanvasImage(url); canvasDescription = '';
    $('#visual-result').textContent = `Ready to edit locally · ${canvas.width} × ${canvas.height}. Describe the result you want.`;
  } catch (error) { $('#visual-result').textContent = error.message; }
  finally { URL.revokeObjectURL(url); event.target.value = ''; setCanvasBusy(false); }
});
$('#undo-canvas').addEventListener('click', () => {
  if (canvasBusy || !canvasUndo.length) return;
  setCanvasBusy(true); const previous = canvasUndo[canvasUndo.length - 1];
  try {
    canvas.width = maskCanvas.width = previous.image.width;
    canvas.height = maskCanvas.height = previous.image.height;
    context.putImageData(previous.image, 0, 0); clearSelection(); canvasHasImage = true;
    canvasDescription = previous.description; canvasUndo.pop(); $('#visual-result').textContent = 'Previous image restored.';
  }
  catch (error) { $('#visual-result').textContent = error.message; }
  finally { setCanvasBusy(false); }
});
$('#clear-canvas').addEventListener('click', () => {
  snapshotCanvas(); context.clearRect(0, 0, canvas.width, canvas.height); clearSelection(); canvasHasImage = false;
  canvasDescription = ''; setCanvasBusy(false);
});
$('#save-canvas').addEventListener('click', () => { const link = document.createElement('a'); link.download = `ORCA-canvas-${new Date().toISOString().slice(0, 10)}.png`; link.href = canvas.toDataURL('image/png'); link.click(); });
async function runCanvasImage(edit = false, selection = false) {
  if (canvasBusy) return;
  const prompt = $('#visual-prompt').value.trim(), target = $('#visual-result');
  if (!prompt) { target.textContent = 'Describe the image you want first.'; return; }
  if (edit && !canvasHasImage) { target.textContent = 'Upload, draw or generate an image first.'; return; }
  if (selection && !maskPainted) { target.textContent = 'Choose Select area to edit, then brush over the part you want changed.'; return; }
  const [width, height] = $('#image-size').value.split('x').map(Number);
  const steps = Number($('#image-quality').value);
  const negativePrompt = $('#negative-prompt').value.trim();
  const seedValue = $('#image-seed').value.trim();
  const common = {prompt, steps, sampler: 'dpmpp_2m', scheduler: 'karras'};
  if (negativePrompt) common.negative_prompt = negativePrompt;
  if (seedValue) common.seed = Number(seedValue);
  const payload = edit ? {...common, strength: Number($('#edit-strength').value) / 100,
    image: canvas.toDataURL('image/png').split(',')[1]} : {...common, width, height};
  if (selection) {
    const mask = document.createElement('canvas'); mask.width = canvas.width; mask.height = canvas.height;
    const ctx = mask.getContext('2d'); ctx.fillStyle = '#000000'; ctx.fillRect(0, 0, mask.width, mask.height);
    ctx.drawImage(maskCanvas, 0, 0); payload.mask = mask.toDataURL('image/png').split(',')[1];
  }
  setCanvasBusy(true);
  target.textContent = `${edit ? 'Editing' : 'Generating'} locally on CRUCIBLE… This can take a few minutes.`;
  try {
    const response = await fetch(edit ? '/api/images/edit' : '/api/images/generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    if (!response.ok) { let detail; try { detail = (await response.json()).error; } catch {} throw Error(detail || `Image request failed (${response.status})`); }
    const url = URL.createObjectURL(await response.blob());
    try { await showCanvasImage(url); } finally { URL.revokeObjectURL(url); }
    canvasDescription = prompt;
    const seed = response.headers.get('X-ORCA-Image-Seed');
    if (seed) $('#image-seed').value = seed;
    target.textContent = `${selection ? 'Selected area edited; the rest is preserved.' : edit ? 'Edited locally; Undo is available.' : 'Generated locally; ready to edit or export.'}${seed ? ` Seed ${seed}.` : ''}`;
  } catch (error) { target.textContent = error.message; }
  finally { setCanvasBusy(false); }
}
$('#generate-image').addEventListener('click', () => runCanvasImage());
$('#edit-image').addEventListener('click', () => runCanvasImage(true));
$('#edit-selection').addEventListener('click', () => runCanvasImage(true, true));
async function runCanvasVideo(animate = false) {
  const prompt = $('#video-prompt').value.trim();
  const target = $('#video-status');
  if (!prompt) { target.textContent = 'Describe the scene and motion first.'; return; }
  if (animate && !canvasHasImage) { target.textContent = 'Upload or generate a Canvas image first.'; return; }
  const [width, height] = $('#video-size').value.split('x').map(Number);
  const payload = {prompt, width, height, length: Number($('#video-length').value),
    steps: 20, fps: 24};
  const seed = $('#video-seed').value.trim(); if (seed) payload.seed = Number(seed);
  if (animate) payload.image = canvas.toDataURL('image/png').split(',')[1];
  setCanvasBusy(true); target.textContent = `${animate ? 'Animating Canvas' : 'Generating video'} on CRUCIBLE… This can take several minutes.`;
  try {
    const response = await fetch(animate ? '/api/videos/animate' : '/api/videos/generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    if (!response.ok) { let detail; try { detail = (await response.json()).error; } catch {} throw Error(detail || `Video request failed (${response.status})`); }
    const blob = await response.blob();
    if (blob.type.split(';')[0] !== 'video/mp4') throw Error('CRUCIBLE returned an unreadable video.');
    if (generatedVideoURL) URL.revokeObjectURL(generatedVideoURL);
    generatedVideoURL = URL.createObjectURL(blob);
    const video = $('#generated-video'); video.src = generatedVideoURL; video.hidden = false;
    const save = $('#save-video'); save.href = generatedVideoURL;
    save.download = `ORCA-video-${Date.now()}.mp4`; save.hidden = false;
    const returnedSeed = response.headers.get('X-ORCA-Image-Seed');
    if (returnedSeed) $('#video-seed').value = returnedSeed;
    target.textContent = `${animate ? 'Canvas image animated' : 'Video generated'} locally. ${response.headers.get('X-ORCA-Video-Frames') || payload.length} frames at ${response.headers.get('X-ORCA-Video-FPS') || payload.fps} fps${returnedSeed ? ` · seed ${returnedSeed}` : ''}.`;
  } catch (error) { target.textContent = error.message; }
  finally { setCanvasBusy(false); }
}
$('#generate-video').addEventListener('click', () => runCanvasVideo(false));
$('#animate-canvas').addEventListener('click', () => runCanvasVideo(true));
$('#develop-visual').addEventListener('click', async () => {
  const prompt = $('#visual-prompt').value.trim(), target = $('#visual-result');
  if (!prompt || canvasBusy) return;
  setCanvasBusy(true); target.textContent = 'Improving the prompt with ORCA…';
  try {
    const result = await postInference(`Write a standalone SDXL image prompt under 1500 characters in summary. Only the prompt, no explanations. Describe the desired visible result, lighting and composition. Current image description (text only, no pixels): ${canvasDescription || 'unknown; do not invent unseen details'}. User direction: ${prompt}`, 'visual');
    $('#visual-prompt').value = result.summary.slice(0, 1500); target.textContent = 'Prompt improved. Review it, then generate or edit.';
  }
  catch (error) { target.textContent = error.message; }
  finally { setCanvasBusy(false); }
});

$('#calculate-ohm').addEventListener('click', () => {
  let status=$('#ohm-status');
  if(!status){status=document.createElement('p');status.id='ohm-status';status.setAttribute('role','status');$('#calculate-ohm').after(status);}
  status.textContent='';
  let voltage = Number($('#ohm-v').value), current = Number($('#ohm-i').value), resistance = Number($('#ohm-r').value);
  const hasV = Number.isFinite(voltage) && $('#ohm-v').value !== '', hasI = Number.isFinite(current) && $('#ohm-i').value !== '', hasR = Number.isFinite(resistance) && $('#ohm-r').value !== '';
  if(Number(hasV)+Number(hasI)+Number(hasR)!==2){status.textContent='Enter exactly two known values. Clear the third input before recalculating.';return;}
  if((hasR && resistance<=0)||(hasV && hasI && current===0)){status.textContent='Resistance must be positive; zero current cannot determine resistance from voltage.';return;}
  if (hasV && hasI) resistance = voltage / current;
  else if (hasV && hasR) current = voltage / resistance;
  else if (hasI && hasR) voltage = current * resistance;
  else return;
  if(![voltage,current,resistance,voltage*current].every(Number.isFinite)||resistance<=0){status.textContent='Inputs do not describe a finite positive-resistance model.';return;}
  $('#ohm-v').value = Number(voltage.toPrecision(8)); $('#ohm-i').value = Number(current.toPrecision(8)); $('#ohm-r').value = Number(resistance.toPrecision(8)); $('#ohm-p').value = Number((voltage * current).toPrecision(8));
  status.textContent='Ideal DC resistor only. Calculated dissipation is not a selected component power rating.';
});
const lengthMeters = { mm: .001, cm: .01, m: 1, in: .0254, ft: .3048 };
$('#convert-units').addEventListener('click', () => { const value = Number($('#convert-value').value), from = $('#convert-from').value, to = $('#convert-to').value, converted = value * lengthMeters[from] / lengthMeters[to]; $('#convert-result').textContent = `${Number(converted.toPrecision(10))} ${to}`; });
$('#run-engineering').addEventListener('click', async () => { const prompt = $('#engineering-prompt').value.trim(), target = $('#engineering-result'); if (!prompt) return; target.textContent = 'Analyzing on CRUCIBLE…'; try { const result = await postInference(`Engineer this problem. Show assumptions, important calculations, failure modes, and a verification plan: ${prompt}`, 'engineer'); target.textContent = `${result.summary}\n\nEvidence\n• ${result.evidence.join('\n• ')}\n\nUncertainty: ${result.uncertainty}`; } catch (error) { target.textContent = error.message; } });

$('#toggle-stop').addEventListener('click', async () => {
  if (mutationPending) return;
  const auth = controlAuth(), reason = $('#stop-reason').value.trim(), result = $('#control-result');
  if (!auth.token || !reason) { result.textContent = 'Identity token and reason are required.'; return; }
  try { const body = await postMutation('/api/control/emergency-stop', { actor: auth.identity, active: !state.emergency_stop, reason }, auth); result.textContent = body.emergency_stop ? 'Emergency stop engaged.' : 'Emergency stop released.'; $('#stop-reason').value = ''; await refresh(); }
  catch (error) { result.textContent = `Control failed: ${error.message}`; }
});
document.addEventListener('click', async event => {
  const approval = event.target.closest('[data-approval]'), pause = event.target.closest('[data-pause-job]'), action = event.target.closest('[data-job-action]');
  if((!approval&&!pause&&!action)||mutationPending)return;
  const auth = controlAuth(), reason = $('#stop-reason').value.trim(), result = $('#control-result');
  if (!auth.token || !reason) { result.textContent = 'Identity token and reason are required in Incidents.'; showOps('incidents'); return; }
  let url, payload, message;
  if (approval) { url = `/api/approvals/${approval.dataset.approval}`; payload = { actor: auth.identity, approve: approval.dataset.decision === 'approve', note: reason }; message = `Approval ${approval.dataset.decision}d.`; }
  else if (pause) { url = `/api/jobs/${pause.dataset.pauseJob}/pause`; payload = { actor: auth.identity, reason }; message = 'Job paused.'; }
  else { const job = state.jobs.find(item => item.id === action.dataset.jobId), verb = action.dataset.jobAction; url = `/api/jobs/${job.id}/${verb}`; payload = verb === 'resume' ? { actor: auth.identity, reason } : verb === 'start' ? { actor: auth.identity } : verb === 'review' ? { actor: auth.identity, reviewer: 'quench' } : { actor: auth.identity, note: reason }; message = `Job ${verb} accepted.`; }
  try { await postMutation(url, payload, auth); result.textContent = message; $('#stop-reason').value = ''; await refresh(); }
  catch (error) { result.textContent = `Control failed: ${error.message}`; }
});

refresh();
setInterval(refresh, 8000);

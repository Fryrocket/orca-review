/* Explicit user commands only. Model replies and retrieved memory never enter this parser. */
const StudioLauncher = (() => {
  const views = {studio: 'studio', chat: 'studio', code: 'projects', canvas: 'canvas',
    inventory: 'inventory', engineering: 'engineering', operations: 'operations',
    'bot monitor': 'bot-monitor', bots: 'bot-monitor',
    business: 'business', quasarvolt: 'business', 'quasar vault': 'business',
    'quasarvolt supply': 'business', 'quasar vault supply': 'business',
    'product builder': 'product-builder', 'product development': 'product-builder'};
  const operationsViews = {fabric: 'fleet', 'system health': 'fleet', fleet: 'fleet',
    'bot creator': 'bot-creator', bots: 'bot-creator', work: 'work', jobs: 'work',
    approvals: 'approvals', evidence: 'evidence', incidents: 'incidents', security: 'security',
    agents: 'agents', connectors: 'connectors', costs: 'costs'};
  const apps = {browser: 'chrome', 'web browser': 'chrome', chrome: 'chrome',
    'google chrome': 'chrome', firefox: 'firefox',
    files: 'files', 'file manager': 'files', calculator: 'calculator',
    'text editor': 'editor', gedit: 'editor', kicad: 'kicad',
    'kicad manager': 'kicad', 'kicad image converter': 'kicad_image_converter',
    'image converter': 'kicad_image_converter', 'bitmap to component': 'kicad_image_converter',
    'kicad pcb calculator': 'kicad_pcb_calculator', 'pcb calculator': 'kicad_pcb_calculator',
    'kicad pcb editor': 'kicad_pcb_editor', 'pcb editor': 'kicad_pcb_editor', pcbnew: 'kicad_pcb_editor',
    'kicad schematic editor': 'kicad_schematic_editor', 'schematic editor': 'kicad_schematic_editor',
    eeschema: 'kicad_schematic_editor', 'kicad gerber viewer': 'kicad_gerber_viewer',
    'gerber viewer': 'kicad_gerber_viewer', gerbview: 'kicad_gerber_viewer',
    freecad: 'freecad', 'free cad': 'freecad',
    libreoffice: 'libreoffice', 'libre office': 'libreoffice',
    'libreoffice writer': 'libreoffice_writer', 'libre office writer': 'libreoffice_writer',
    writer: 'libreoffice_writer', 'libreoffice calc': 'libreoffice_calc',
    'libre office calc': 'libreoffice_calc', 'libreoffice calculator': 'libreoffice_calc',
    'libre office calculator': 'libreoffice_calc', calc: 'libreoffice_calc',
    'libreoffice draw': 'libreoffice_draw', 'libre office draw': 'libreoffice_draw',
    draw: 'libreoffice_draw', 'libreoffice impress': 'libreoffice_impress',
    'libre office impress': 'libreoffice_impress', impress: 'libreoffice_impress',
    'libreoffice math': 'libreoffice_math', 'libre office math': 'libreoffice_math',
    'archive manager': 'archive_manager', calendar: 'calendar', characters: 'characters',
    chatbox: 'chatbox', camera: 'cheese', cheese: 'cheese',
    'document scanner': 'document_scanner', scanner: 'document_scanner',
    'document viewer': 'document_viewer', 'pdf viewer': 'document_viewer',
    fonts: 'fonts', 'font viewer': 'fonts', 'image viewer': 'image_viewer',
    'power statistics': 'power_statistics', rhythmbox: 'rhythmbox',
    'music player': 'rhythmbox', shotwell: 'shotwell', 'photo manager': 'shotwell',
    thunderbird: 'thunderbird', mail: 'thunderbird', email: 'thunderbird',
    'to do': 'todo', tasks: 'todo', videos: 'videos', 'video player': 'videos',
    help: 'help'};
  const sites = {'google drive': 'https://drive.google.com/', 'quasarvolt drive': 'https://drive.google.com/drive/folders/1gDmk8L_NyVi6Hc7kSjIAQyhiAAyYOYl_',
    erpnext: 'https://erpnext.com/', paperless: 'https://docs.paperless-ngx.com/',
    documenso: 'https://docs.documenso.com/', metabase: 'https://www.metabase.com/docs/latest/',
    notion: 'https://www.notion.so/',
    linear: 'https://linear.app/', 'google photos': 'https://photos.google.com/',
    muse: 'https://ai.meta.com/muse/shopping/', 'meta muse': 'https://ai.meta.com/muse/shopping/',
    'chatgpt finances': 'https://chatgpt.com/', finances: 'https://chatgpt.com/',
    shopify: 'https://accounts.shopify.com/store-login',
    'amazon seller': 'https://sellercentral.amazon.com/', 'seller central': 'https://sellercentral.amazon.com/',
    'ebay seller': 'https://www.ebay.com/sh/ovw',
    'alibaba seller': 'https://seller.alibaba.com/', 'alibaba.com seller': 'https://seller.alibaba.com/',
    'temu seller': 'https://seller.temu.com/', aws: 'https://console.aws.amazon.com/',
    easyeda: 'https://easyeda.com/editor', 'easyeda editor': 'https://easyeda.com/editor',
    'kicad documentation': 'https://docs.kicad.org/'};
  function webURL(value) {
    if (typeof value !== 'string' || value.length > 2048 || /[\s\\]/.test(value)) return null;
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null;
      return url.href;
    } catch { return null; }
  }
  function parse(text) {
    const match = /^(?:(?:hey\s+)?orca[, ]+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:open|launch|show|use|take me to)\s+(.+?)\s*[.!?]?$/i.exec(text.trim());
    if (!match) return null;
    const target = match[1].replace(/\s+please$/i, '').replace(/^the\s+/i, '');
    const key = target.toLowerCase();
    if (Object.hasOwn(views, key)) return {kind: 'view', target: views[key], label: key};
    if (Object.hasOwn(operationsViews, key)) return {kind: 'operations', target: operationsViews[key], label: key};
    if (Object.hasOwn(apps, key)) return {kind: 'app', target: apps[key], label: key};
    if (Object.hasOwn(sites, key)) return {kind: 'app', target: 'chrome', url: sites[key], label: key};
    if (/^(?:[a-z][a-z0-9+.-]*:|www\.)/i.test(target) || /^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\/\S*)?$/i.test(target)) {
      const url = webURL(/^[a-z][a-z0-9+.-]*:/i.test(target) ? target : `https://${target}`);
      return url ? {kind: 'app', target: 'chrome', url, label: url} : {kind: 'error', label: 'Only HTTP or HTTPS websites without embedded passwords can be opened.'};
    }
    return null;
  }
  function parseTask(text) {
    if (typeof text !== 'string' || text.length > 12000) return null;
    const match = /^(?:(?:hey\s+)?orca[, ]+)?(?:(?:can|could|would|will) you\s+)?(?:please\s+)?(?:use|work (?:in|with)|in)\s+(.+)$/i.exec(text.trim());
    if (!match || /\b(?:don't|do not|never)\s+(?:use|open|launch)\b/i.test(text)) return null;
    const remainder = match[1].replace(/\s*[.!?]?$/, '');
    const choices = [
      ...Object.entries(views).map(([label, target]) => ({label, kind: 'view', target})),
      ...Object.entries(operationsViews).map(([label, target]) => ({label, kind: 'operations', target})),
      ...Object.entries(apps).map(([label, target]) => ({label, kind: 'app', target})),
      ...Object.entries(sites).map(([label, url]) => ({label, kind: 'app', target: 'chrome', url})),
    ].sort((left, right) => right.label.length - left.label.length);
    for (const choice of choices) {
      const pattern = new RegExp(`^${choice.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s+(?:to|for)\\s+(.+)$`, 'i');
      const task = pattern.exec(remainder);
      if (task?.[1]?.trim()) return {...choice, kind: 'task', launchKind: choice.kind, task: task[1].trim()};
      const colon = new RegExp(`^${choice.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*[:,]\\s*(.+)$`, 'i').exec(remainder);
      if (colon?.[1]?.trim()) return {...choice, kind: 'task', launchKind: choice.kind, task: colon[1].trim()};
    }
    return null;
  }
  function parseProject(text) {
    if (typeof text !== 'string' || text.length > 2000) return null;
    const value = text.trim();
    if (!/^(?:(?:hey\s+)?orca[, ]+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:let'?s\s+)?(?:create|build|design|make|lay out)\b/i.test(value)) return null;
    if (!/\b(?:ai[- ]powered\s+)?dog\s+(?:food\s+)?feeder\b/i.test(value)) return null;
    if (/\b(?:don't|do not|explain|describe|how (?:do|would)|example|pretend)\b/i.test(value)) return null;
    return {kind: 'project', prompt: value};
  }
  function parseRead(text) {
    if (typeof text !== 'string' || text.length > 2400) return null;
    const match = /^(?:(?:hey\s+)?orca[, ]+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:read|inspect|research)\s+(https:\/\/\S+)\s*[.!?]?$/i.exec(text.trim());
    if (!match || /\b(?:submit|buy|purchase|publish|send|sign in|log in)\b/i.test(text)) return null;
    const url = webURL(match[1]);
    return url ? {url} : null;
  }
  const pending = new Map();
  if (typeof window !== 'undefined') window.addEventListener('orca-launch-result', event => {
    const result = event.detail;
    const callback = pending.get(result?.id);
    if (callback) { pending.delete(result.id); callback(result); }
  });
  function launch(command) {
    const handler = globalThis.webkit?.messageHandlers?.orcaLauncher;
    if (!handler) return Promise.resolve({ok: false, message: 'App launching requires the updated native KILN Studio app. Open it on KILN; an ordinary browser or the iPhone prototype cannot launch KILN apps.'});
    const id = globalThis.crypto.randomUUID();
    return new Promise(resolve => {
      const timer = setTimeout(() => { pending.delete(id); resolve({ok: false, message: 'No launch confirmation received. Check KILN before retrying.'}); }, 15000);
      pending.set(id, result => { clearTimeout(timer); resolve(result); });
      try { handler.postMessage(JSON.stringify({id, app: command.target, url: command.url || ''})); }
      catch { clearTimeout(timer); pending.delete(id); resolve({ok: false, message: 'KILN could not receive the app request.'}); }
    });
  }
  function createProject(plan) {
    const handler = globalThis.webkit?.messageHandlers?.orcaLauncher;
    if (!handler) return Promise.resolve({ok: false, message: 'Project creation requires the native KILN Studio app.'});
    const id = globalThis.crypto.randomUUID();
    return new Promise(resolve => {
      const timer = setTimeout(() => { pending.delete(id); resolve({ok: false, message: 'No project confirmation received. Check KILN before retrying.'}); }, 30000);
      pending.set(id, result => { clearTimeout(timer); resolve(result); });
      try { handler.postMessage(JSON.stringify({id, action: 'create_project', plan})); }
      catch { clearTimeout(timer); pending.delete(id); resolve({ok: false, message: 'KILN could not receive the project request.'}); }
    });
  }
  function openArtifact(kind, path) {
    const handler = globalThis.webkit?.messageHandlers?.orcaLauncher;
    if (!handler) return Promise.resolve({ok: false, message: 'Opening project artifacts requires native KILN Studio.'});
    const id = globalThis.crypto.randomUUID();
    return new Promise(resolve => {
      const timer = setTimeout(() => { pending.delete(id); resolve({ok: false, message: 'No app confirmation received.'}); }, 15000);
      pending.set(id, result => { clearTimeout(timer); resolve(result); });
      try { handler.postMessage(JSON.stringify({id, action: 'open_artifact', kind, path})); }
      catch { clearTimeout(timer); pending.delete(id); resolve({ok: false, message: 'KILN could not receive the artifact request.'}); }
    });
  }
  function saveCadDraft(filename, content) {
    const handler = globalThis.webkit?.messageHandlers?.orcaLauncher;
    if (!handler) return Promise.resolve({ok: false, message: 'Saving and opening CAD files requires native KILN Studio. You can still download the board from chat.'});
    const id = globalThis.crypto.randomUUID();
    return new Promise(resolve => {
      const timer = setTimeout(() => { pending.delete(id); resolve({ok: false, message: 'No CAD save confirmation received.'}); }, 20000);
      pending.set(id, result => { clearTimeout(timer); resolve(result); });
      try { handler.postMessage(JSON.stringify({id, action: 'save_cad_draft', filename, content})); }
      catch { clearTimeout(timer); pending.delete(id); resolve({ok: false, message: 'KILN could not receive the CAD draft.'}); }
    });
  }
  function readPage(url) {
    const handler = globalThis.webkit?.messageHandlers?.orcaLauncher;
    if (!handler) return Promise.resolve({ok: false, message: 'Page reading requires native KILN Studio.'});
    const id = globalThis.crypto.randomUUID();
    return new Promise(resolve => {
      const timer = setTimeout(() => { pending.delete(id); resolve({ok: false, message: 'Private browser read timed out.'}); }, 45000);
      pending.set(id, result => { clearTimeout(timer); resolve(result); });
      try { handler.postMessage(JSON.stringify({id, action: 'read_browser_page', url})); }
      catch { clearTimeout(timer); pending.delete(id); resolve({ok: false, message: 'KILN could not receive the browser read request.'}); }
    });
  }
  return {parse, parseTask, parseProject, parseRead, webURL, launch, createProject, openArtifact, saveCadDraft, readPage};
})();

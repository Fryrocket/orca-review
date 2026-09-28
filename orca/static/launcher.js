/* Explicit user commands only. Model replies and retrieved memory never enter this parser. */
const StudioLauncher = (() => {
  const views = {studio: 'studio', chat: 'studio', code: 'projects', canvas: 'canvas',
    inventory: 'inventory', engineering: 'engineering', operations: 'operations',
    business: 'business', quasarvolt: 'business', 'quasarvolt supply': 'business'};
  const apps = {browser: 'browser', 'web browser': 'browser', firefox: 'firefox',
    files: 'files', 'file manager': 'files', calculator: 'calculator',
    'text editor': 'editor', gedit: 'editor', kicad: 'kicad',
    'kicad manager': 'kicad', 'kicad image converter': 'kicad_image_converter',
    'image converter': 'kicad_image_converter', 'bitmap to component': 'kicad_image_converter',
    'kicad pcb calculator': 'kicad_pcb_calculator', 'pcb calculator': 'kicad_pcb_calculator',
    'kicad pcb editor': 'kicad_pcb_editor', 'pcb editor': 'kicad_pcb_editor', pcbnew: 'kicad_pcb_editor',
    'kicad schematic editor': 'kicad_schematic_editor', 'schematic editor': 'kicad_schematic_editor',
    eeschema: 'kicad_schematic_editor', libreoffice: 'libreoffice', 'libre office': 'libreoffice',
    'libreoffice writer': 'libreoffice_writer', 'libre office writer': 'libreoffice_writer',
    writer: 'libreoffice_writer', 'libreoffice calc': 'libreoffice_calc',
    'libre office calc': 'libreoffice_calc', 'libreoffice calculator': 'libreoffice_calc',
    'libre office calculator': 'libreoffice_calc', calc: 'libreoffice_calc',
    'libreoffice draw': 'libreoffice_draw', 'libre office draw': 'libreoffice_draw',
    draw: 'libreoffice_draw', 'libreoffice impress': 'libreoffice_impress',
    'libre office impress': 'libreoffice_impress', impress: 'libreoffice_impress',
    'libreoffice math': 'libreoffice_math', 'libre office math': 'libreoffice_math'};
  const sites = {'google drive': 'https://drive.google.com/', 'quasarvolt drive': 'https://drive.google.com/drive/folders/1gDmk8L_NyVi6Hc7kSjIAQyhiAAyYOYl_',
    erpnext: 'https://erpnext.com/', paperless: 'https://docs.paperless-ngx.com/',
    documenso: 'https://docs.documenso.com/', metabase: 'https://www.metabase.com/docs/latest/',
    notion: 'https://www.notion.so/',
    linear: 'https://linear.app/', 'google photos': 'https://photos.google.com/',
    muse: 'https://ai.meta.com/muse/', 'meta muse': 'https://ai.meta.com/muse/',
    shopify: 'https://accounts.shopify.com/store-login',
    'amazon seller': 'https://sellercentral.amazon.com/', 'seller central': 'https://sellercentral.amazon.com/',
    'ebay seller': 'https://www.ebay.com/sh/ovw',
    'alibaba seller': 'https://seller.alibaba.com/', 'alibaba.com seller': 'https://seller.alibaba.com/',
    'temu seller': 'https://seller.temu.com/', aws: 'https://console.aws.amazon.com/'};
  function webURL(value) {
    if (typeof value !== 'string' || value.length > 2048 || /[\s\\]/.test(value)) return null;
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null;
      return url.href;
    } catch { return null; }
  }
  function parse(text) {
    const match = /^(?:(?:hey\s+)?orca[, ]+)?(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:open|launch|show|take me to)\s+(.+?)\s*[.!?]?$/i.exec(text.trim());
    if (!match) return null;
    const target = match[1].replace(/\s+please$/i, '').replace(/^the\s+/i, '');
    const key = target.toLowerCase();
    if (Object.hasOwn(views, key)) return {kind: 'view', target: views[key], label: key};
    if (Object.hasOwn(apps, key)) return {kind: 'app', target: apps[key], label: key};
    if (Object.hasOwn(sites, key)) return {kind: 'app', target: 'browser', url: sites[key], label: key};
    if (/^(?:[a-z][a-z0-9+.-]*:|www\.)/i.test(target) || /^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:\/\S*)?$/i.test(target)) {
      const url = webURL(/^[a-z][a-z0-9+.-]*:/i.test(target) ? target : `https://${target}`);
      return url ? {kind: 'app', target: 'browser', url, label: url} : {kind: 'error', label: 'Only HTTP or HTTPS websites without embedded passwords can be opened.'};
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
  return {parse, parseProject, webURL, launch, createProject, openArtifact};
})();

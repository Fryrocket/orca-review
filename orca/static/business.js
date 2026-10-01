const agenticBusinessContract = `Operate agentically inside the approved scope. Inspect current connected evidence before assuming facts. Make a short execution plan, select and use the relevant available tools, perform safe and reversible work, verify outputs and calculations, and save useful artifacts, sources, decisions, and next state. Continue until the requested outcome is complete or a real approval or authority boundary is reached. Do not stop merely to explain what could be done. Ask only when missing information would materially change the result. Never invent access, evidence, account state, certification, filing, purchase, contract, message, publication, refund, recall, or completed external action. Pause for explicit approval before spending money, contacting people, accepting terms, publishing, filing, certifying, refunding, recalling, deleting, exposing a service, changing security or permissions, or making another irreversible external commitment.`;

let stagedBusinessWorkflow = null;
globalThis.ORCABusinessWorkflow = Object.freeze({
  stage(workflow) { stagedBusinessWorkflow = workflow; },
  take(prompt) {
    if (!stagedBusinessWorkflow || !prompt.startsWith(agenticBusinessContract)) return null;
    const workflow = stagedBusinessWorkflow;
    stagedBusinessWorkflow = null;
    return workflow;
  },
  clear() { stagedBusinessWorkflow = null; }
});

const businessWorkflowTitle = button => {
  const container = button.closest('article') || button.closest('section');
  return container?.querySelector('h3, strong, h2')?.textContent?.trim()
    || button.textContent.trim() || 'Business workflow';
};

const businessWorkflowID = (button, index) => {
  const slug = businessWorkflowTitle(button).toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80);
  return `business-${String(index + 1).padStart(2, '0')}-${slug || 'workflow'}`;
};

document.querySelectorAll('[data-business-prompt]').forEach((button, index) => {
  const workflow = Object.freeze({
    id: businessWorkflowID(button, index),
    title: businessWorkflowTitle(button)
  });
  button.dataset.businessWorkflow = workflow.id;
  button.addEventListener('click', async () => {
    const prompt = button.dataset.businessPrompt?.trim();
    const input = document.querySelector('#prompt-input');
    if (!prompt || !input) return;
    show('studio');
    selectMode('auto');
    globalThis.ORCABusinessWorkflow.stage(workflow);
    input.value = `${agenticBusinessContract}\n\n${prompt}`;
    input.focus();
    const status = document.querySelector('#business-app-status');
    const tool = button.dataset.businessTool;
    if (tool && businessSites[tool]) {
      if (status) status.textContent = `Workflow staged. Opening ${tool === 'muse' ? 'Meta Muse' : 'the research tool'} for ORCA…`;
      const result = await StudioLauncher.launch({kind: 'app', target: 'browser', url: businessSites[tool]});
      if (status) status.textContent = `${result.message} Return the sourced findings to this staged workflow, then press Enter; ORCA will score, verify, and record them.`;
    } else if (status) status.textContent = 'Workflow staged. Add details, then press Enter to create a tracked ORCA job and run it.';
  });
});

const businessSites = Object.freeze({
  google_drive: 'https://drive.google.com/drive/folders/1gDmk8L_NyVi6Hc7kSjIAQyhiAAyYOYl_',
  erpnext: 'https://erpnext.com/',
  paperless: 'https://docs.paperless-ngx.com/',
  documenso: 'https://docs.documenso.com/',
  metabase: 'https://www.metabase.com/docs/latest/',
  muse: 'https://ai.meta.com/muse/',
  shopify: 'https://accounts.shopify.com/store-login',
  amazon_seller: 'https://sellercentral.amazon.com/',
  ebay_seller: 'https://www.ebay.com/sh/ovw',
  alibaba_seller: 'https://seller.alibaba.com/',
  temu_seller: 'https://seller.temu.com/',
  aws: 'https://console.aws.amazon.com/',
  chatgpt_finances: 'https://chatgpt.com/'
});
document.querySelectorAll('[data-business-site]').forEach(button => {
  button.addEventListener('click', async () => {
    const url = businessSites[button.dataset.businessSite];
    const status = document.querySelector('#business-app-status');
    if (!url || button.disabled) return;
    button.disabled = true;
    if (status) status.textContent = 'Opening the official service in KILN Studio…';
    try {
      const result = await StudioLauncher.launch({kind: 'app', target: 'browser', url});
      if (status) status.textContent = result.message;
    } finally { button.disabled = false; }
  });
});

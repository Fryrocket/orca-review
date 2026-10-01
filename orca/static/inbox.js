(() => {
  let messages = [];
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const headers = () => ({'X-ORCA-Identity': studioAuth.identity,
    'X-ORCA-Identity-Token': studioAuth.token});
  function render() {
    const query = document.querySelector('#inbox-search')?.value.trim().toLowerCase() || '';
    const category = document.querySelector('#inbox-category')?.value || '';
    const priority = document.querySelector('#inbox-priority-filter')?.value || '';
    const rows = messages.filter(message => (!category || message.category === category)
      && (!priority || message.priority === priority)
      && (!query || [message.sender_display,message.subject,message.project_or_customer,
        message.summary,message.follow_up].some(value => String(value).toLowerCase().includes(query))));
    const container = document.querySelector('#inbox-list');
    if (!container) return;
    container.innerHTML = rows.length ? rows.map(message => `<article class="inbox-message">
      <header><div><span class="inbox-meta">${safe(message.category)} · ${safe(message.priority)}</span><h3>${safe(message.subject)}</h3><small>${safe(message.sender_display)} · ${safe(message.received_at)}</small></div><span class="truth">${safe(message.project_or_customer)}</span></header>
      <p>${safe(message.summary)}</p><p><b>Follow-up:</b> ${safe(message.follow_up)}${message.deadline ? ` · <b>Deadline:</b> ${safe(message.deadline)}` : ''}</p>
      ${message.draft_reply ? `<p class="inbox-draft"><b>Draft only:</b> ${safe(message.draft_reply)}</p>` : ''}
      ${message.uncertainty ? `<p><b>Review:</b> ${safe(message.uncertainty)}</p>` : ''}</article>`).join('')
      : '<p>No matching email summaries.</p>';
  }
  async function load() {
    const status = document.querySelector('#inbox-status');
    try {
      const response = await fetch('/api/inbox', {headers: headers()});
      const body = await response.json();
      if (!response.ok) throw Error(body.error || 'Inbox is unavailable.');
      messages = body.messages || [];
      document.querySelector('#inbox-total').textContent = messages.length;
      document.querySelector('#inbox-followups').textContent = messages.filter(x => x.follow_up && x.follow_up !== 'none').length;
      document.querySelector('#inbox-priority').textContent = messages.filter(x => ['high','urgent'].includes(x.priority)).length;
      document.querySelector('#inbox-connection').textContent = messages.length
        ? `${messages.length} privacy-minimized summaries imported through governed Muse handoffs.`
        : 'Connected workspace ready; no Muse email summaries imported yet.';
      render();
    } catch (error) { if (status) status.textContent = error.message; }
  }
  async function openMuse() {
    const status = document.querySelector('#inbox-status');
    const objective = 'Organize my authorized QuasarVolt email for ORCA Inbox. Group threads, summarize minimally, identify deadlines and follow-ups, and prepare drafts only.';
    try {
      const response = await fetch('/api/business/muse/email-handoff', {method:'POST',
        headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({
          workflow_id:'business-24-muse-email',objective})});
      const body = await response.json();
      if (!response.ok) throw Error(body.error || 'Muse email handoff failed.');
      try { await navigator.clipboard.writeText(body.muse_prompt); } catch {}
      const result = await StudioLauncher.launch({kind:'app',target:'browser',url:body.official_url});
      status.textContent = `${result.message} The read-only email prompt was copied when permitted. Paste the returned JSON package here.`;
    } catch (error) { status.textContent = error.message; }
  }
  async function importPacket() {
    const status = document.querySelector('#inbox-status');
    try {
      const parsed = JSON.parse(document.querySelector('#inbox-import-json').value);
      const response = await fetch('/api/inbox/import', {method:'POST',headers:{...headers(),
        'Content-Type':'application/json'},body:JSON.stringify({request_id:mutationKey(),
          handoff_id:parsed.handoff_id,messages:parsed.messages})});
      const body = await response.json();
      if (!response.ok) throw Error(body.error || 'Inbox import failed.');
      status.textContent = `${body.imported} summaries validated. No raw bodies, attachments, sends, or mailbox changes.`;
      document.querySelector('#inbox-import-json').value = '';
      await load();
    } catch (error) { status.textContent = error.message || 'The returned package is not valid JSON.'; }
  }
  document.querySelector('#inbox-refresh')?.addEventListener('click', load);
  document.querySelector('#inbox-open-muse')?.addEventListener('click', openMuse);
  document.querySelector('#inbox-import')?.addEventListener('click', importPacket);
  ['#inbox-search','#inbox-category','#inbox-priority-filter'].forEach(selector =>
    document.querySelector(selector)?.addEventListener('input', render));
  globalThis.ORCAInbox = Object.freeze({load});
})();

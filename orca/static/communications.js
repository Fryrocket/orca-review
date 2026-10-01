(() => {
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const headers = () => ({'X-ORCA-Identity': studioAuth.identity,
    'X-ORCA-Identity-Token': studioAuth.token});
  const empty = '<p>Nothing needs attention.</p>';
  const setList = (selector, rows, renderer) => {
    const node = document.querySelector(selector);
    if (node) node.innerHTML = rows.length ? rows.map(renderer).join('') : empty;
  };
  async function load() {
    const status = document.querySelector('#communications-status');
    try {
      const response = await fetch('/api/communications', {headers: headers()});
      const body = await response.json();
      if (!response.ok) throw Error(body.error || 'Communications Hub is unavailable.');
      const counts = body.counts || {};
      document.querySelector('#communications-relationships').textContent = counts.relationships || 0;
      document.querySelector('#communications-followups').textContent = counts.follow_ups || 0;
      document.querySelector('#communications-deadlines').textContent = counts.deadlines || 0;
      document.querySelector('#communications-quarantined').textContent = counts.quarantined || 0;
      document.querySelector('#communications-headline').textContent = body.daily_brief?.headline || 'No briefing available.';
      setList('#communications-top-actions', body.daily_brief?.top_actions || [], task =>
        `<article><b>${safe(task.subject)}</b><small>${safe(task.association)} · ${safe(task.priority)} · propose ${safe(task.proposed_workspace)}</small><p>${safe(task.action)}</p></article>`);
      setList('#communications-tasks', body.tasks || [], task =>
        `<article><b>${safe(task.subject)}</b><small>${safe(task.association)} · ${safe(task.priority)} · ${safe(task.proposed_workspace)} / ${safe(task.proposed_owner)}${task.deadline ? ` · ${safe(task.deadline)}` : ''}</small><p>${safe(task.action)}</p></article>`);
      setList('#communications-calendar', body.calendar_candidates || [], item =>
        `<article><b>${safe(item.title)}</b><small>${safe(item.association)} · candidate only</small><p>${safe(item.when)}</p></article>`);
      setList('#communications-timelines', body.timelines || [], timeline =>
        `<article><b>${safe(timeline.association)}</b><small>${timeline.message_count} message(s) · ${timeline.open_follow_ups} follow-up(s)</small><p>${timeline.recent_subjects.map(safe).join(' · ')}</p></article>`);
      setList('#communications-quarantine', body.quarantine || [], message =>
        `<article><b>${safe(message.subject)}</b><small>${safe(message.sender_display)} · isolated summary</small><p>${safe(message.uncertainty || message.summary)}</p></article>`);
      status.textContent = `${counts.messages || 0} minimized summaries analyzed. No external or mailbox actions were taken.`;
    } catch (error) { if (status) status.textContent = error.message; }
  }
  document.querySelector('#communications-refresh')?.addEventListener('click', load);
  document.querySelector('#communications-open-inbox')?.addEventListener('click', () =>
    document.querySelector('[data-view="inbox"]')?.click());
  globalThis.ORCACommunications = Object.freeze({load});
})();

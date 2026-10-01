(() => {
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function load() {
    const status = document.querySelector('#solo-operator-status');
    try {
      const response = await fetch('/api/solo-operator/system');
      const body = await response.json();
      if (!response.ok) throw Error(body.error || 'Action Center is unavailable.');
      const modules = body.modules || [];
      document.querySelector('#solo-operator-total').textContent = modules.length;
      document.querySelector('#solo-operator-candidates').textContent = modules.filter(x => x.state.includes('candidate')).length;
      document.querySelector('#solo-operator-staged').textContent = modules.filter(x => x.state === 'staged').length;
      document.querySelector('#solo-operator-grid').innerHTML = modules.map(module => `<article>
        <header><span>${safe(module.state.replaceAll('_',' '))}</span><b>${safe(module.name)}</b></header>
        <p>${safe(module.purpose)}</p><small>${module.owners.map(safe).join(' · ')}</small><em>${safe(module.mode.replaceAll('_',' '))}</em>
      </article>`).join('');
      document.querySelector('#solo-operator-boundaries').innerHTML = body.boundaries.map(item => `<span>${safe(item)}</span>`).join('');
      status.textContent = `${modules.length} control rooms registered. External actions taken: ${body.external_actions}.`;
    } catch (error) { if (status) status.textContent = error.message; }
  }
  document.querySelector('#solo-operator-refresh')?.addEventListener('click', load);
  document.querySelector('#solo-operator-brief')?.addEventListener('click', () => {
    const input = document.querySelector('#prompt-input');
    if (!input) return;
    document.querySelector('[data-view="studio"]')?.click();
    input.value = 'Prepare my ORCA Action Center briefing. Inspect only connected, approved evidence across communications, customers and vendors, knowledge, cases, quarantined items, commitments, consent, failed work, business memory, decisions, performance, money, orders, inventory, fleet health, approvals, and deadlines. Deduplicate items, preserve source references, distinguish measured facts from staged or unavailable data, rank by urgency and consequence, and give me the three most important next actions. Do not send messages, change records, replay failed work, publish, spend, move money, modify permissions, or claim an unconnected system is live.';
    input.focus();
  });
  globalThis.ORCASoloOperator = Object.freeze({load});
})();

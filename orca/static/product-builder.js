(() => {
  const phases = [
    ['discovery','Discovery'],['requirements','Requirements'],['architecture','Architecture'],
    ['feasibility','Feasibility'],['detailed_design','Detailed design'],['prototype','Prototype'],
    ['verification','Verification'],['manufacturing','Manufacturing'],['launch','Launch'],['lifecycle','Lifecycle']
  ];
  const root = document.querySelector('#builder-pipeline');
  if (!root) return;
  let currentPlan = null;
  root.innerHTML = phases.map(([id,label]) => `<div class="builder-stage" data-builder-stage="${id}"><strong>${label}</strong><span>Waiting</span></div>`).join('');
  const rows = (items, renderer, empty = 'None recorded.') => items?.length ? items.map(renderer).join('') : `<p>${esc(empty)}</p>`;
  const mark = state => ['ready','available','connected_record_only'].includes(state) ? 'pass' : state === 'required' ? 'blocked' : 'waiting';
  const setStage = (id, state, detail) => {
    const node = document.querySelector(`[data-builder-stage="${id}"]`);
    if (!node) return;
    node.className = `builder-stage ${state === 'ready' ? 'done' : state === 'running' ? 'running' : ''}`;
    node.querySelector('span').textContent = detail;
  };

  function renderPlan(result) {
    const plan = result.plan;
    currentPlan = plan;
    document.querySelector('#builder-product').textContent = plan.product_name;
    document.querySelector('#builder-product-id').textContent = plan.product_id;
    document.querySelector('#builder-maturity').textContent = plan.maturity.toUpperCase();
    document.querySelector('#builder-release').textContent = plan.release_state.replaceAll('_',' ');
    document.querySelector('#builder-requirement-count').textContent = plan.requirements.length;
    document.querySelector('#builder-risk-score').textContent = Math.max(...plan.risks.map(item => item.rpn));
    plan.phases.forEach(phase => setStage(phase.id, phase.status, phase.status === 'ready' ? 'Ready to work' : 'Waiting on prior gate'));
    document.querySelector('#builder-tracks').innerHTML = plan.tracks.map(track => `<article><span>${esc(track.owner)}</span><strong>${esc(track.name)}</strong><p>${esc(track.purpose)}</p></article>`).join('');
    document.querySelector('#builder-requirements').innerHTML = `<table class="builder-table"><thead><tr><th>ID</th><th>Category</th><th>Requirement</th><th>Acceptance method</th><th>State</th></tr></thead><tbody>${plan.requirements.map(item => `<tr><td><code>${esc(item.id)}</code></td><td>${esc(item.category)}</td><td>${esc(item.statement)}</td><td>${esc(item.verification)}</td><td><span class="builder-pill">${esc(item.status)}</span></td></tr>`).join('')}</tbody></table>`;
    document.querySelector('#builder-risks').innerHTML = rows(plan.risks, risk => `<div class="builder-risk"><div><b>${esc(risk.id)} · ${esc(risk.hazard)}</b><span>RPN ${esc(risk.rpn)}</span></div><small>S${esc(risk.severity)} · O${esc(risk.occurrence)} · D${esc(risk.detection)} · ${esc(risk.owner)}</small><p>${esc(risk.control)}</p></div>`);
    document.querySelector('#builder-gates').innerHTML = rows(plan.approval_gates, gate => `<div class="builder-row"><i class="builder-mark blocked"></i><div><b>${esc(gate.gate)}</b><small>${esc(gate.authority)} · ${esc(gate.status)}</small></div></div>`);
    document.querySelector('#builder-resources').innerHTML = rows(plan.tool_plan, tool => `<div class="builder-row"><i class="builder-mark ${mark(tool.state)}"></i><div><b>${esc(tool.name)}</b><small>${esc(tool.purpose)} · ${esc(tool.state.replaceAll('_',' '))}</small></div></div>`);
    document.querySelector('#builder-have').innerHTML = `<div class="builder-row"><i class="builder-mark ${plan.inventory.state === 'available' ? 'pass' : 'waiting'}"></i><div><b>${esc(plan.inventory.items_seen)} inventory records inspected</b><small>${esc(plan.inventory.warning)}</small></div></div>`;
    document.querySelector('#builder-root').textContent = `${plan.product_id}/ · canonical record ${result.record.record_hash.slice(0,12)} · job ${result.job.id}`;
    document.querySelector('#builder-files').innerHTML = plan.deliverables.map(file => `<div class="builder-file"><span>└</span><div><b>${esc(file.path)}</b><small>${esc(file.name)} · ${esc(file.format)} · ${esc(file.state)}</small></div><code>${esc(file.id)}</code></div>`).join('');
    document.querySelector('#builder-next').innerHTML = plan.next_actions.map((action,index) => `<div class="builder-row"><i class="builder-step">${index + 1}</i><div><b>${esc(action)}</b></div></div>`).join('');
    const pcb = document.querySelector('#builder-create-pcb');
    pcb.disabled = !plan.legacy_pcb_draft_supported;
    document.querySelector('#builder-prototype-note').textContent = plan.legacy_pcb_draft_supported
      ? 'This concept matches the supported dog-feeder PCB prototype. You may create a separate, editable KiCad draft; it will remain blocked from manufacturing release.'
      : 'No automatic CAD generator is approved for this product yet. Complete requirements and architecture first; ORCA will then select the correct engineering tools.';
  }

  document.querySelector('#builder-form').addEventListener('submit', async event => {
    event.preventDefault();
    const prompt = document.querySelector('#builder-prompt').value.trim();
    const button = document.querySelector('#builder-run');
    if (!prompt || button.disabled) return;
    button.disabled = true;
    document.querySelector('#builder-state').textContent = 'PLANNING';
    document.querySelector('#builder-state').className = 'builder-state running';
    document.querySelector('#builder-status').textContent = 'Building a governed product program and inspecting available inventory evidence…';
    phases.forEach(([id]) => setStage(id, '', 'Waiting'));
    setStage('discovery','running','Creating concept record');
    try {
      await refresh();
      const result = await postMutation('/api/product-development/plans', {prompt}, controlAuth());
      renderPlan(result);
      document.querySelector('#builder-state').textContent = 'CONCEPT RECORDED';
      document.querySelector('#builder-state').className = 'builder-state';
      document.querySelector('#builder-status').textContent = 'Product program created and sent to QUENCH review. No parts were allocated, files released, suppliers contacted, or manufacturing claims made.';
      await refresh();
    } catch (error) {
      document.querySelector('#builder-state').textContent = 'NEEDS ATTENTION';
      document.querySelector('#builder-state').className = 'builder-state';
      document.querySelector('#builder-status').textContent = error.message;
    } finally { button.disabled = false; }
  });

  document.querySelector('#builder-create-pcb').addEventListener('click', async event => {
    if (!currentPlan?.legacy_pcb_draft_supported || event.currentTarget.disabled) return;
    const button = event.currentTarget;
    button.disabled = true;
    document.querySelector('#builder-status').textContent = 'Creating the supported editable KiCad prototype on KILN…';
    try {
      const plan = await postProjectPlan(currentPlan.brief);
      const outcome = await StudioLauncher.createProject(plan);
      if (!outcome.ok) throw Error(outcome.message);
      const project = outcome.project;
      document.querySelector('#builder-legacy-output').hidden = false;
      document.querySelector('#builder-schematic').innerHTML = `<div class="builder-diagram">${plan.components.map(component => `<div class="builder-block"><strong>${esc(component.ref)}</strong><span>${esc(component.value)}</span><div class="builder-nets">${[...new Set(Object.values(component.pins))].map(net => `<i>${esc(net)}</i>`).join('')}</div></div>`).join('')}</div>`;
      document.querySelector('#builder-checks').innerHTML = rows(project.checks, check => `<div class="builder-row"><i class="builder-mark ${esc(check.status)}"></i><div><b>${esc(check.name)}</b><small>${esc(check.detail)}</small></div></div>`);
      document.querySelector('#builder-need').innerHTML = rows(plan.missing_parts, item => `<div class="builder-row"><i class="builder-mark waiting"></i><div><b>${esc(item.quantity)} × ${esc(item.part)}</b><small>${esc(item.reason)}</small></div></div>`);
      const artifacts = [['board','Open PCB',project.board],['schematic','Open schematic',project.schematic],['bom','Open BOM',project.bom],['folder','Open folder',project.folder]];
      document.querySelector('#builder-artifacts').innerHTML = artifacts.map(([kind,label,path]) => `<button type="button" data-builder-open="${esc(kind)}" data-path="${esc(path)}">${esc(label)}</button>`).join('');
      document.querySelector('#builder-status').textContent = `${outcome.message} The prototype remains paused for engineering review.`;
    } catch (error) {
      document.querySelector('#builder-status').textContent = error.message;
      button.disabled = false;
    }
  });

  document.querySelector('#builder-artifacts').addEventListener('click', async event => {
    const button = event.target.closest('[data-builder-open]');
    if (!button) return;
    button.disabled = true;
    try {
      const result = await StudioLauncher.openArtifact(button.dataset.builderOpen, button.dataset.path);
      document.querySelector('#builder-status').textContent = result.message;
    } finally { button.disabled = false; }
  });
})();

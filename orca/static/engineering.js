/* UI inputs carry explicit units; no HTML from model or server results is executed. */
const engineeringUnits = {
  'Ω': [['Ω',1],['kΩ',1e3],['MΩ',1e6]], 'F':[['F',1],['µF',1e-6],['nF',1e-9],['pF',1e-12]],
  'H':[['H',1],['mH',1e-3],['µH',1e-6]], 'Hz':[['Hz',1],['kHz',1e3],['MHz',1e6]],
  'A':[['A',1],['mA',1e-3]], 'V':[['V',1],['mV',1e-3]], 'm':[['m',1],['mm',1e-3],['cm',1e-2]],
  'm²':[['m²',1],['mm²',1e-6],['cm²',1e-4]], 'm⁴':[['m⁴',1],['mm⁴',1e-12]],
  'Pa':[['Pa',1],['kPa',1e3],['MPa',1e6],['GPa',1e9]], 'N':[['N',1],['kN',1e3]],
  'N·m':[['N·m',1],['N·mm',1e-3]], 'fraction':[['fraction',1],['%',.01]]
};
function engineeringSI(text, factor) {
  if (typeof text !== 'string' || !text.trim()) throw Error('Every input needs a value; blanks are not zero.');
  const value = Number(text) * Number(factor);
  if (!Number.isFinite(value)) throw Error('Enter finite numbers in the selected units.');
  return value;
}
async function engineeringPost(path, data) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json',
    'X-ORCA-Identity':studioAuth.identity, 'X-ORCA-Identity-Token':studioAuth.token},body:JSON.stringify(data)});
  const body = await response.json();
  if (!response.ok || body.status === 'error') throw Error(body.error || `Calculation failed (${response.status})`);
  return body;
}
function scienceFields() {
  const op = $('#science-operation').value;
  const matrix = ['matrix_determinant','matrix_inverse','linear_solve','eigenvalues'].includes(op);
  $('#science-expression-field').hidden = matrix;
  $('#science-variable-field').hidden = !['differentiate','integrate','definite_integral','solve'].includes(op);
  $('#science-domain-field').hidden = op !== 'solve';
  $('#science-bounds').hidden = op !== 'definite_integral';
  $('#science-matrix-field').hidden = !matrix;
  $('#science-rhs-field').hidden = op !== 'linear_solve';
  $('#science-result').textContent = 'Ready. Results are recalculated only when you press Calculate.';
}
$('#science-operation').addEventListener('change', scienceFields);
$('#science-example').addEventListener('click', () => {
  const op = $('#science-operation').value;
  const examples = {evaluate:'(10^40+1)-10^40',simplify:'(x^2-1)/(x-1)',differentiate:'sin(x)*exp(x)',
    integrate:'x^2',definite_integral:'x^2',solve:'x^2-2'};
  $('#science-expression').value = examples[op] || '';
  $('#science-variable').value = 'x'; $('#science-lower').value = '0'; $('#science-upper').value = '3';
  $('#science-matrix').value = '[["2","1"],["1","-1"]]'; $('#science-rhs').value = '["5","1"]';
  $('#science-result').textContent = 'Example loaded. Review it, then calculate.';
});
$('#science-form').addEventListener('submit', async event => {
  event.preventDefault(); const button=$('#science-run'), target=$('#science-result');
  if (button.disabled) return;
  button.disabled=true; target.textContent='Computing locally…';
  try {
    const operation=$('#science-operation').value;
    const payload={operation,precision:Number($('#science-precision').value)};
    if (!$('#science-expression-field').hidden) payload.expression=$('#science-expression').value.trim();
    if (!$('#science-variable-field').hidden) payload.variable=$('#science-variable').value.trim();
    if (operation==='solve') payload.domain=$('#science-domain').value;
    if (operation==='definite_integral') {payload.lower=$('#science-lower').value.trim();payload.upper=$('#science-upper').value.trim();}
    if (!$('#science-matrix-field').hidden) payload.matrix=JSON.parse($('#science-matrix').value);
    if (operation==='linear_solve') payload.rhs=JSON.parse($('#science-rhs').value);
    const result=await engineeringPost('/api/science',payload);
    target.textContent = `${result.status==='unresolved'?'Unresolved expression—not a completed solution':'Exact result'}\n${result.exact}\n\nNumerical preview (${result.precision_digits || payload.precision} digits)\n${result.numeric ?? 'Not available'}\n\n${(result.notes || []).join('\n')}`;
  } catch(error) {target.textContent=error.message;}
  finally {button.disabled=false;}
});
let engineeringCatalog={};
function renderEngineeringFields() {
  const spec=engineeringCatalog[$('#engineering-tool').value];
  if (!spec) return;
  $('#engineering-formula').textContent=spec.formula;
  $('#engineering-assumptions').textContent=spec.assumptions;
  const container=$('#engineering-fields'); container.replaceChildren();
  for (const field of spec.fields) {
    const label=document.createElement('label'); label.textContent=field.label;
    const row=document.createElement('div'); row.className='engineering-field-value';
    const input=document.createElement('input'); input.type='number'; input.step='any'; input.required=true;
    input.id=`eng-${field.key}`; input.setAttribute('aria-label',field.label); input.placeholder=String(field.example);
    const select=document.createElement('select'); select.id=`eng-unit-${field.key}`; select.setAttribute('aria-label',`${field.label} unit`);
    for (const [name,factor] of engineeringUnits[field.unit] || [[field.unit,1]]) {
      const option=document.createElement('option'); option.value=String(factor); option.textContent=name; select.append(option);
    }
    row.append(input,select); label.append(row); container.append(label);
  }
  $('#engineering-model-result').textContent='Enter your values. Placeholder examples are not submitted.';
}
$('#engineering-tool').addEventListener('change',renderEngineeringFields);
$('#engineering-example').addEventListener('click',()=>{
  const spec=engineeringCatalog[$('#engineering-tool').value]; if(!spec)return;
  for(const field of spec.fields){$(`#eng-${field.key}`).value=field.example;$(`#eng-unit-${field.key}`).value='1';}
  $('#engineering-model-result').textContent='Example inputs loaded—not measurements from your design.';
});
$('#engineering-model-form').addEventListener('submit',async event=>{
  event.preventDefault(); const button=$('#engineering-model-run'), target=$('#engineering-model-result');
  if(button.disabled)return; button.disabled=true;
  try {
    const tool=$('#engineering-tool').value, spec=engineeringCatalog[tool];
    if(!spec)throw Error('Engineering catalog is unavailable.');
    const values={};
    for(const field of spec.fields)values[field.key]=engineeringSI($(`#eng-${field.key}`).value,$(`#eng-unit-${field.key}`).value);
    target.textContent='Calculating model…'; const result=await engineeringPost('/api/engineering',{tool,values});
    const outputs=Object.entries(result.outputs).map(([key,value])=>`${key.replaceAll('_',' ')}: ${Number(value.toPrecision(12))}`);
    target.textContent=`${outputs.join('\n')}\n\nFormula: ${result.formula}\n\nAssumptions: ${result.assumptions}\n\n${result.warnings.length?'Warnings: '+result.warnings.join('\n')+'\n\n':''}${result.notice}`;
  }catch(error){target.textContent=error.message;}finally{button.disabled=false;}
});
(async()=>{
  try {
    const response=await fetch('/api/engineering/catalog'); if(!response.ok)throw Error('Engineering catalog unavailable.');
    engineeringCatalog=await response.json(); const select=$('#engineering-tool'); select.replaceChildren();
    for(const category of ['Electronics','Mechanical']){
      const group=document.createElement('optgroup');group.label=category;
      for(const [key,spec] of Object.entries(engineeringCatalog))if(spec.category===category){
        const option=document.createElement('option');option.value=key;option.textContent=spec.title;group.append(option);
      }
      select.append(group);
    }
    renderEngineeringFields();
  }catch(error){$('#engineering-model-result').textContent=error.message;}
})();
scienceFields();

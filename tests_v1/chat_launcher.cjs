const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({URL});
vm.runInContext(fs.readFileSync('orca/static/launcher.js', 'utf8') + '\nglobalThis.launcher = StudioLauncher;', context);
const {parse, parseTask, parseProject, webURL} = context.launcher;
for (const text of ['Open Canvas', 'can you open the canvas?', 'Orca, please open canvas', 'show canvas please']) {
  assert.equal(parse(text).target, 'canvas', text);
}
for (const [text, target] of [['open studio', 'studio'], ['open code', 'projects'],
  ['open canvas', 'canvas'], ['open inventory', 'inventory'],
  ['open engineering', 'engineering'], ['open operations', 'operations'],
  ['open Quasar Vault', 'business'], ['open product builder', 'product-builder']]) {
  assert.equal(parse(text).target, target, text);
}
for (const [text, target] of [['open web browser', 'chrome'], ['open Chrome', 'chrome'],
  ['launch firefox', 'firefox'],
  ['open files', 'files'], ['open calculator', 'calculator'], ['open text editor', 'editor'],
  ['open KiCad', 'kicad'], ['open KiCad image converter', 'kicad_image_converter'],
  ['open PCB calculator', 'kicad_pcb_calculator'], ['open PCB editor', 'kicad_pcb_editor'],
  ['open schematic editor', 'kicad_schematic_editor'], ['open Gerber viewer', 'kicad_gerber_viewer'],
  ['open FreeCAD', 'freecad'], ['open LibreOffice', 'libreoffice'],
  ['open Writer', 'libreoffice_writer'], ['open LibreOffice calculator', 'libreoffice_calc'],
  ['open LibreOffice Draw', 'libreoffice_draw'], ['open Impress', 'libreoffice_impress'],
  ['open LibreOffice Math', 'libreoffice_math'], ['open document scanner', 'document_scanner'],
  ['open PDF viewer', 'document_viewer'], ['open image viewer', 'image_viewer'],
  ['open Thunderbird', 'thunderbird'], ['open video player', 'videos'],
  ['open calendar', 'calendar'], ['open archive manager', 'archive_manager']]) {
  assert.equal(parse(text).target, target);
}
assert.equal(parse('open notion').target, 'chrome');
assert.equal(parse('open notion').url, 'https://www.notion.so/');
assert.equal(parse('open quasarvolt drive').url, 'https://drive.google.com/drive/folders/1gDmk8L_NyVi6Hc7kSjIAQyhiAAyYOYl_');
assert.equal(parse('open erpnext').url, 'https://erpnext.com/');
assert.equal(parse('open paperless').url, 'https://docs.paperless-ngx.com/');
assert.equal(parse('open documenso').url, 'https://docs.documenso.com/');
assert.equal(parse('open metabase').url, 'https://www.metabase.com/docs/latest/');
assert.equal(parse('open easyeda').url, 'https://easyeda.com/editor');
assert.equal(parse('open kicad documentation').url, 'https://docs.kicad.org/');
assert.equal(parse('open product builder').target, 'product-builder');
assert.equal(parse('use inventory').target, 'inventory');
assert.equal(parse('open system health').target, 'fleet');
assert.equal(parse('open bot creator').target, 'bot-creator');
assert.equal(parse('open example.com').url, 'https://example.com/');
assert.deepEqual(JSON.parse(JSON.stringify(parseTask('use FreeCAD to design an enclosure'))),
  {label: 'freecad', kind: 'task', target: 'freecad', launchKind: 'app', task: 'design an enclosure'});
assert.deepEqual(JSON.parse(JSON.stringify(parseTask('use inventory to find 100 uF capacitors'))),
  {label: 'inventory', kind: 'task', target: 'inventory', launchKind: 'view', task: 'find 100 uF capacitors'});
assert.deepEqual(JSON.parse(JSON.stringify(parseTask('in engineering, calculate a voltage divider'))),
  {label: 'engineering', kind: 'task', target: 'engineering', launchKind: 'view', task: 'calculate a voltage divider'});
assert.deepEqual(JSON.parse(JSON.stringify(parseTask('in Quasar Vault: research a product'))),
  {label: 'quasar vault', kind: 'task', target: 'business', launchKind: 'view', task: 'research a product'});
assert.equal(parseTask('explain how to use FreeCAD to design an enclosure'), null);
assert.equal(parseTask('do not use FreeCAD to change this file'), null);
for (const text of ['Do not open calculator', 'Explain how to open firefox', 'open terminal',
  'open calculator and delete files', 'He said "open files"', 'open __proto__', 'open constructor']) {
  assert.equal(parse(text), null, text);
}
for (const value of ['javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,hi',
  'https://user:password@example.com', 'https://example.com\\evil', 'https://example.com\n']) {
  assert.equal(webURL(value), null, value);
}
assert.equal(parse('open javascript:alert(1)').kind, 'error');
assert.equal(parse('open file:///etc/passwd').kind, 'error');
assert.equal(parseProject("let's create an efficient AI-powered dog feeder").kind, 'project');
assert.equal(parseProject('explain how to build a dog feeder'), null);
assert.equal(parseProject('build a weather station'), null);
context.launcher.launch({target: 'files'}).then(result => {
  assert.equal(result.ok, false);
  assert.match(result.message, /native KILN/);
  console.log('Chat launcher tests passed');
});

const app = fs.readFileSync('orca/static/app.js', 'utf8');
const calls = [];
const runContext = vm.createContext({StudioLauncher: context.launcher,
  inferencePending: false, activeMode: 'auto', conversationHistory: [],
  routes: {auto: {}, reason: {}}, $: () => ({disabled: false}),
  wantsChatImage: () => false, wantsChatVideo: () => false, wantsChatPCB: () => false,
  boundedHistory: () => [],
  appendUserMessage: () => {}, appendThinking: () => {},
  show: id => calls.push(['show', id]), appendAssistant: value => calls.push(['reply', value.summary]),
  showOps: id => calls.push(['ops', id]),
  rememberConversation: async () => {},
  postChat: async () => { throw Error('Explicit launcher must not call the model'); }
});
vm.runInContext(app.slice(app.indexOf('async function runPrompt('), app.indexOf("$('#prompt-form').addEventListener")), runContext);
(async () => {
  await runContext.runPrompt('open canvas');
  assert.deepEqual(calls.shift(), ['show', 'canvas']);
  assert.deepEqual(calls.shift(), ['reply', 'Opened canvas.']);
  await runContext.runPrompt('open calculator');
  assert.match(calls.shift()[1], /requires the updated native KILN/);
  await runContext.runPrompt('open bot creator');
  assert.deepEqual(calls.shift(), ['ops', 'bot-creator']);
  assert.deepEqual(calls.shift(), ['reply', 'Opened bot creator.']);
  assert.equal(runContext.inferencePending, false);
  console.log('Chat launcher integration checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('orca/static/app.js', 'utf8');
const start = source.indexOf('function wantsChatImage(');
const end = source.indexOf('async function generateChatImage(', start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);
for (const prompt of ['Create a photo of a forest', 'Please generate an image of a cat',
  'Can you make me a realistic picture of a cabin?', '/image a full moon']) {
  assert.equal(context.wantsChatImage(prompt, 'reason'), true, prompt);
}
for (const prompt of ['How do I create a photo?', 'Explain image generation',
  'Do not generate an image', 'Create a photo editor in Python', 'Hello']) {
  assert.equal(context.wantsChatImage(prompt, 'reason'), false, prompt);
}
assert.equal(context.wantsChatImage('A red fox in snow', 'photo'), true);
assert.equal(context.wantsChatImage('/image a cat', 'code'), true);
console.log('Chat image intent tests passed');

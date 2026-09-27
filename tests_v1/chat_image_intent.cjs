const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('orca/static/app.js', 'utf8');
const start = source.indexOf('function wantsChatImage(');
const end = source.indexOf('async function generateChatImage(', start);
const context = vm.createContext({});
vm.runInContext(source.slice(start, end), context);
for (const prompt of ['Create a photo of a forest', 'Please generate an image of a cat',
  'Can you make me a realistic picture of a cabin?', '/image a full moon',
  'I want you to generate a photo of a fox', 'I would like a picture of a forest',
  'Generate a new image of a cabin', 'Create a nighttime forest photo',
  'Draw a cat', 'Can you please create a photo of a mountain']) {
  assert.equal(context.wantsChatImage(prompt, 'reason'), true, prompt);
}
for (const prompt of ['How do I create a photo?', 'Explain image generation',
  'Do not generate an image', 'Create a photo editor in Python', 'Hello']) {
  assert.equal(context.wantsChatImage(prompt, 'reason'), false, prompt);
}
assert.equal(context.wantsChatImage('A red fox in snow', 'photo'), true);
assert.equal(context.wantsChatImage('/image a cat', 'code'), true);
assert.equal(context.wantsChatImage('Create an image of a cabin', 'visual'), true);
assert.equal(context.wantsChatImage('Can you create an image generator app?', 'reason'), false);
assert.equal(context.wantsChatImage('Please do not create a photo', 'reason'), false);
console.log('Chat image intent tests passed');

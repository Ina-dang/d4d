const {test} = require('node:test');
const assert = require('node:assert/strict');

test('gateway routes API, download and UI paths to the same backend without credentials', async () => {
  const {buildConfig} = await import('../deploy/vercel/build.mjs');
  const config = buildConfig('https://backend.example.com');
  const route = config.routes[0];
  for (const path of ['/api/scenarios', '/api/scenarios/run-id',
      '/api/collections/run-id/analysis/report/download', '/storyboard/storyboard.html']) {
    const match = path.match(new RegExp('^' + route.src + '$'));
    assert.equal(route.dest.replace('$1', match[1]), 'https://backend.example.com' + path);
  }
  assert.equal(config.version, 3);
  assert.equal(route.headers['Cache-Control'], 'no-store');
});

test('gateway fails instead of publishing a localhost or secret-bearing target', async () => {
  const {buildConfig} = await import('../deploy/vercel/build.mjs');
  for (const value of [undefined, '', 'http://backend.example.com', 'https://localhost',
      'https://127.0.0.1', 'https://[::1]', 'https://user:password@backend.example.com',
      'https://backend.example.com/api', 'https://backend.example.com?token=secret']) {
    assert.throws(() => buildConfig(value));
  }
});

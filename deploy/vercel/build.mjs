// Vercel gateway for the existing persistent Python application.
// No Python runtime, credentials, source data or model files are uploaded here.
import {mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';

export function buildConfig(raw) {
  let backend;
  try { backend = new URL(raw); } catch { throw new Error('BACKEND_ORIGIN에 Python 서버의 HTTPS 주소를 설정하세요.'); }
  if (backend.protocol !== 'https:' || backend.username || backend.password ||
      backend.pathname !== '/' || backend.search || backend.hash ||
      backend.hostname === 'localhost' || backend.hostname.endsWith('.localhost') ||
      backend.hostname === '[::1]' || /^127\./.test(backend.hostname)) {
    throw new Error('BACKEND_ORIGIN은 경로·인증정보 없는 공개 HTTPS origin이어야 합니다.');
  }
  return {
    version: 3,
    routes: [{src: '/(.*)', dest: `${backend.origin}/$1`, headers: {'Cache-Control': 'no-store'}}],
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const config = buildConfig(process.env.BACKEND_ORIGIN);
  const output = new URL('./.vercel/output/', import.meta.url);
  await mkdir(new URL('static/', output), {recursive: true});
  await writeFile(new URL('config.json', output), JSON.stringify(config, null, 2) + '\n');
  console.log('Vercel gateway build completed. Python/model/storage run on the configured backend.');
}

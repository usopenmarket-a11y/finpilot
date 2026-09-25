const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const ts = require('typescript');
const { NextRequest, NextResponse } = require('next/server');

// Execute the real route/middleware with only Supabase I/O substituted.
function load(relativePath, mocks, env = {}) {
  const filename = path.join(__dirname, '..', relativePath);
  const compiled = ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, {
    module, exports: module.exports, process: { env }, URL,
    require: name => name in mocks ? mocks[name] : require(name),
  }, { filename });
  return module.exports;
}

function callback(error = null, env = { NEXT_PUBLIC_SITE_URL: 'https://finpilot.example' }) {
  return load('src/app/auth/callback/route.ts', {
    '@/lib/supabase/server': { createClient: async () => ({
      auth: { exchangeCodeForSession: async () => ({ error }) },
    }) },
  }, env).GET;
}

test('recovery code exchange redirects to password entry', async () => {
  const response = await callback()(new Request('https://finpilot.example/auth/callback?code=test&next=/auth/update-password'));
  assert.equal(response.headers.get('location'), 'https://finpilot.example/auth/update-password');
});

test('ordinary sign-in still redirects to dashboard', async () => {
  const response = await callback()(new Request('https://finpilot.example/auth/callback?code=test'));
  assert.equal(response.headers.get('location'), 'https://finpilot.example/dashboard');
});

test('callback rejects arbitrary redirect targets', async () => {
  for (const next of ['https://attacker.example', '//attacker.example', '/auth/update-password/../../evil']) {
    const response = await callback()(new Request(`https://finpilot.example/auth/callback?code=test&next=${encodeURIComponent(next)}`));
    assert.equal(response.headers.get('location'), 'https://finpilot.example/dashboard');
  }
});

test('missing or expired codes lead to login errors', async () => {
  const missing = await callback()(new Request('https://finpilot.example/auth/callback'));
  assert.equal(missing.headers.get('location'), 'https://finpilot.example/auth/login?error=missing_code');
  const expired = await callback({ message: 'expired' })(new Request('https://finpilot.example/auth/callback?code=expired&next=/auth/update-password'));
  assert.equal(expired.headers.get('location'), 'https://finpilot.example/auth/login?error=auth_failed');
});

test('unconfigured public origin uses a safe relative redirect without throwing', async () => {
  const response = await callback(null, {})(new Request('https://untrusted.example/auth/callback?code=test&next=/auth/update-password'));
  assert.equal(response.status, 303);
  assert.equal(response.headers.get('location'), '/auth/update-password');
});

function middleware(user) {
  return load('src/lib/supabase/middleware.ts', {
    '@supabase/ssr': { createServerClient: (_url, _key, options) => ({
      auth: { getUser: async () => {
        options.cookies.setAll([{ name: 'session', value: 'refreshed-test-session', options: { path: '/' } }]);
        return { data: { user } };
      } },
    }) },
    'next/server': { NextResponse },
  }).updateSession;
}

test('signed-in recovery and callback requests reach their handlers', async () => {
  for (const route of ['/auth/update-password', '/auth/callback?code=test']) {
    const response = await middleware({ id: 'test-user' })(new NextRequest(`https://finpilot.example${route}`));
    assert.equal(response.headers.get('location'), null);
    assert.equal(response.cookies.get('session').value, 'refreshed-test-session');
  }
});

test('normal auth redirects retain refreshed session cookies', async () => {
  const response = await middleware({ id: 'test-user' })(new NextRequest('https://finpilot.example/auth/login'));
  assert.equal(response.headers.get('location'), 'https://finpilot.example/dashboard');
  assert.equal(response.cookies.get('session').value, 'refreshed-test-session');
});

test('unauthenticated dashboard requests redirect to login', async () => {
  const response = await middleware(null)(new NextRequest('https://finpilot.example/dashboard'));
  assert.equal(response.headers.get('location'), 'https://finpilot.example/auth/login');
});

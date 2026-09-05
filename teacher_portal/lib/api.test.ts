import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { api, setToken, restoreSession, logoutSession } from './api.ts';
import { GET, POST } from '../app/api/backend/[...path]/route.ts';
const originalFetch = globalThis.fetch;

await test('logout waits for cookie rotation and blocks new refreshes until it finishes', async () => {
  const pending = Promise.withResolvers<Response>();
  let rotated = false;
  let loggedOut = false;
  let seenAuthorization: string | null = null;
  globalThis.fetch = async (url, options) => {
    const path = url instanceof Request ? url.url : url.toString();
    if (path.endsWith('/auth/refresh')) return pending.promise;
    if (path.endsWith('/auth/logout')) {
      assert.equal(rotated, true);
      loggedOut = true;
      return Response.json({ ok: true });
    }
    seenAuthorization = new Headers(options?.headers).get('Authorization');
    return Response.json([]);
  };
  const restoring = restoreSession();
  const leaving = logoutSession();
  assert.equal(await restoreSession(), false);
  assert.equal(loggedOut, false);
  rotated = true;
  pending.resolve(Response.json({ access_token: 'old-teacher-refreshed' }));
  await restoring;
  await leaving;
  await api('/teacher/classes');
  assert.equal(loggedOut, true);
  assert.equal(seenAuthorization, null);
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  setToken(null);
});

await test('a late failed refresh cannot clear a newer login', async () => {
  const pending = Promise.withResolvers<Response>();
  let seenAuthorization: string | null = null;
  globalThis.fetch = async (url, options) => {
    const path = url instanceof Request ? url.url : url.toString();
    if (path.endsWith('/auth/refresh')) return pending.promise;
    seenAuthorization = new Headers(options?.headers).get('Authorization');
    return Response.json([]);
  };
  const restoring = restoreSession();
  setToken('new-teacher');
  pending.resolve(new Response(null, { status: 401 }));
  assert.equal(await restoring, false);
  await api('/teacher/classes');
  assert.equal(seenAuthorization, 'Bearer new-teacher');
});

await test('expired requests share one refresh and retry with the new bearer token', async () => {
  setToken('expired');
  let refreshes = 0;
  globalThis.fetch = async (url, options) => {
    if (
      (url instanceof Request ? url.url : url.toString()).endsWith(
        '/auth/refresh',
      )
    ) {
      refreshes++;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return Response.json({ access_token: 'fresh' });
    }
    return new Headers(options?.headers).get('Authorization') === 'Bearer fresh'
      ? Response.json({ ok: true })
      : new Response(null, { status: 401 });
  };
  assert.deepEqual(
    await Promise.all([api('/teacher/classes'), api('/teacher/classes')]),
    [{ ok: true }, { ok: true }],
  );
  assert.equal(refreshes, 1);
});
await test('permission failure stays a permission failure and does not refresh', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return Response.json({ detail: 'Forbidden' }, { status: 403 });
  };
  await assert.rejects(api('/teacher/classes'), { status: 403 });
  assert.equal(calls, 1);
});
await test('proxy preserves multipart bytes, bearer auth and refresh cookie', async () => {
  let forwarded = false;
  globalThis.fetch = async (url, options) => {
    assert.equal(
      url instanceof Request ? url.url : url.toString(),
      'http://127.0.0.1:8000/teacher/classes/abc/assignments',
    );
    assert.equal(
      new Headers(options?.headers).get('authorization'),
      'Bearer teacher',
    );
    assert.equal(await new Response(options?.body).text(), 'exercise bytes');
    forwarded = true;
    return Response.json(
      { id: 'set' },
      { headers: { 'set-cookie': 'refresh_token=rotated; HttpOnly; Path=/' } },
    );
  };
  const response = await POST(
    new Request(
      'http://localhost:3000/api/backend/teacher/classes/abc/assignments',
      {
        method: 'POST',
        headers: {
          authorization: 'Bearer teacher',
          origin: 'http://localhost:3000',
          'content-type': 'multipart/form-data; boundary=test',
        },
        body: 'exercise bytes',
      },
    ),
    {
      params: Promise.resolve({
        path: ['teacher', 'classes', 'abc', 'assignments'],
      }),
    },
  );
  assert.equal(response.status, 200);
  assert.ok(forwarded);
  assert.match(response.headers.get('set-cookie')!, /HttpOnly/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
});
await test('proxy refuses foreign origins and paths outside the allowed API', async () => {
  globalThis.fetch = async () => {
    throw new Error('Must not reach upstream');
  };
  const denied = await POST(
    new Request('http://localhost:3000/api/backend/auth/login', {
      method: 'POST',
      headers: { origin: 'https://foreign.example' },
    }),
    { params: Promise.resolve({ path: ['auth', 'login'] }) },
  );
  assert.equal(denied.status, 403);
  const missing = await GET(
    new Request('http://localhost:3000/api/backend/private'),
    { params: Promise.resolve({ path: ['private'] }) },
  );
  assert.equal(missing.status, 404);
});

// Same-origin bridge to the existing FastAPI API; the browser cannot select a host.
async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (
    !['auth', 'teacher'].includes(path[0]) ||
    path.some((part) => !/^[a-zA-Z0-9_-]+$/.test(part))
  )
    return Response.json({ detail: 'Not found' }, { status: 404 });
  const origin = request.headers.get('origin');
  if (
    request.method !== 'GET' &&
    origin &&
    origin !== new URL(request.url).origin
  )
    return Response.json({ detail: 'Invalid origin' }, { status: 403 });
  const upstream = new URL(
    path.join('/'),
    `${process.env.BACKEND_URL || 'http://127.0.0.1:8000'}/`,
  );
  upstream.search = new URL(request.url).search;
  const headers = new Headers();
  for (const name of ['content-type', 'authorization', 'cookie']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.method === 'GET' ? undefined : request.body,
      redirect: 'manual',
      signal: AbortSignal.timeout(30_000),
      duplex: 'half',
    } as RequestInit & { duplex: string });
    const outgoing = new Headers({ 'Cache-Control': 'no-store' });
    outgoing.set(
      'Content-Type',
      response.headers.get('content-type') || 'application/json',
    );
    for (const cookie of response.headers.getSetCookie())
      outgoing.append('Set-Cookie', cookie);
    return new Response(response.body, {
      status: response.status,
      headers: outgoing,
    });
  } catch {
    return Response.json({ detail: 'Backend unavailable' }, { status: 502 });
  }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;

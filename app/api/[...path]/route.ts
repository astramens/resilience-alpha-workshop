import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params
  if (Number(request.headers.get('content-length') || 0) > 65536) return NextResponse.json({detail:'Requête trop volumineuse.'}, {status:413})
  const isAuth = ['auth', 'customer', 'face-agent', 'device'].includes(path[0]) || (path[0] === 'admin' && path[1] === 'users')
  const base = isAuth ? process.env.AUTH_INTERNAL_URL || 'http://auth:8001' : process.env.API_INTERNAL_URL || 'http://backend:8000'
  const target = new URL(`/api/${path.map(encodeURIComponent).join('/')}`, base)
  target.search = request.nextUrl.search
  const headers = new Headers()
  for (const name of ['cookie', 'content-type', 'origin', 'authorization', 'stripe-signature']) {
    const value = request.headers.get(name)
    if (value) headers.set(name, value)
  }
  // The edge overwrites this header from its peer address. The frontend has no public port.
  headers.set('x-rearm-client-ip', request.headers.get('x-rearm-client-ip') || 'unknown')
  try {
    const response = await fetch(target, { method: request.method, headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer(),
      cache: 'no-store', signal: AbortSignal.timeout(35000), redirect: 'manual' })
    const result = new NextResponse(await response.arrayBuffer(), { status: response.status })
    for (const name of ['content-type', 'cache-control']) {
      const value = response.headers.get(name)
      if (value) result.headers.set(name, value)
    }
    for (const cookie of response.headers.getSetCookie()) result.headers.append('set-cookie', cookie)
    return result
  } catch {
    return NextResponse.json({ detail: 'API inaccessible. Vérifiez les conteneurs et la base de données.' }, { status: 503 })
  }
}
export { proxy as GET, proxy as POST }

import { NextRequest, NextResponse } from 'next/server'
export const dynamic = 'force-dynamic'
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params
  const target = new URL(`/api/${path.map(encodeURIComponent).join('/')}`, process.env.API_INTERNAL_URL || 'http://backend:8000')
  target.search = request.nextUrl.search
  const headers = new Headers()
  for (const name of ['cookie', 'content-type', 'origin', 'authorization']) {
    const value = request.headers.get(name)
    if (value) headers.set(name, value)
  }
  try {
    const response = await fetch(target, { method: request.method, headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.text(),
      cache: 'no-store', signal: AbortSignal.timeout(12000), redirect: 'manual' })
    const result = new NextResponse(await response.arrayBuffer(), { status: response.status })
    for (const name of ['content-type', 'set-cookie', 'cache-control']) {
      const value = response.headers.get(name)
      if (value) result.headers.set(name, value)
    }
    return result
  } catch {
    return NextResponse.json({ detail: 'API inaccessible. Vérifiez les conteneurs et la base de données.' }, { status: 503 })
  }
}
export { proxy as GET, proxy as POST }

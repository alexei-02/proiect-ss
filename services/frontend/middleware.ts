import { NextRequest, NextResponse } from 'next/server';

export function middleware(req: NextRequest) {
  const token = req.cookies.get('access_token')?.value;
  if (!token && !req.nextUrl.pathname.startsWith('/login')) {
    return NextResponse.redirect(new URL('/login', req.url));
  }
  return NextResponse.next();
}

// Exclude API routes (proxied to the FastAPI backend) and Next.js internals.
export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};

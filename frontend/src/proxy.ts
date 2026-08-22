import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

const forbiddenApprovalQueryKeys = new Set(['handoff', 'approval', 'token', 'nonce']);

export function proxy(request: NextRequest) {
  const safeUrl = request.nextUrl.clone();
  let rejected = false;
  for (const key of Array.from(safeUrl.searchParams.keys())) {
    if (!forbiddenApprovalQueryKeys.has(key.toLowerCase())) continue;
    safeUrl.searchParams.delete(key);
    rejected = true;
  }
  if (!rejected) return NextResponse.next();
  safeUrl.searchParams.set('approval_error', 'query_secret');
  const response = NextResponse.redirect(safeUrl, 307);
  response.headers.set('Cache-Control', 'no-store');
  response.headers.set('Referrer-Policy', 'no-referrer');
  return response;
}

export const config = {
  matcher: '/admin/command/task-suggestions',
};

export interface TokenPayload {
  sub: string;
  username: string;
  roles: string[];
  exp: number;
}

export function decodeToken(token: string): TokenPayload | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload as TokenPayload;
  } catch {
    return null;
  }
}

export function hasRole(token: string, ...roles: string[]): boolean {
  const payload = decodeToken(token);
  if (!payload) return false;
  return roles.some(r => payload.roles.includes(r));
}

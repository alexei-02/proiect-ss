'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, usePathname } from 'next/navigation';
import { decodeToken } from '@/lib/auth';

const NAV_ITEMS = [
  { label: 'Dashboard', href: '/dashboard', roles: ['admin', 'auditor'] },
  { label: 'Review Queue', href: '/review-queue', roles: ['admin', 'doctor', 'receptionist'] },
  { label: 'Reports', href: '/reports', roles: ['admin', 'auditor'] },
  { label: 'Alerts', href: '/alerts', roles: ['admin', 'doctor', 'auditor'] },
  { label: 'Audit Log', href: '/audit-log', roles: ['admin', 'auditor'] },
];

export default function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const [roles, setRoles] = useState<string[]>([]);
  const [username, setUsername] = useState<string>('');

  // Re-read the cookie whenever the route changes so login/logout reflect immediately.
  useEffect(() => {
    const token = document.cookie.match(/access_token=([^;]+)/)?.[1] ?? '';
    const payload = decodeToken(token);
    if (payload) {
      setRoles(payload.roles ?? []);
      setUsername(payload.username ?? '');
    } else {
      setRoles([]);
      setUsername('');
    }
  }, [pathname]);

  // No sidebar on the login screen — nothing to navigate to.
  if (pathname?.startsWith('/login')) return null;

  function logout() {
    document.cookie = 'access_token=; Max-Age=0; path=/';
    setRoles([]);
    setUsername('');
    router.push('/login');
  }

  const visibleItems = NAV_ITEMS.filter(item =>
    item.roles.some(r => roles.includes(r))
  );

  return (
    <aside className="flex h-screen w-56 flex-col bg-gray-900 text-white">
      <div className="px-6 py-5 border-b border-gray-700">
        <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">Medical OCR</p>
        {username && (
          <p className="mt-1 text-sm text-gray-300 truncate">{username}</p>
        )}
      </div>
      <nav className="flex-1 px-3 py-4 space-y-1">
        {visibleItems.map(item => (
          <Link
            key={item.href}
            href={item.href}
            className="block rounded-md px-3 py-2 text-sm font-medium text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="px-3 py-4 border-t border-gray-700">
        <button
          onClick={logout}
          className="w-full rounded-md px-3 py-2 text-sm font-medium text-gray-300 hover:bg-red-700 hover:text-white transition-colors text-left"
        >
          Log out
        </button>
      </div>
    </aside>
  );
}

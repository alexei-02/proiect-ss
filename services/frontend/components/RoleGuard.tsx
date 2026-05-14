'use client';
import { useEffect, useState } from 'react';
import { hasRole } from '@/lib/auth';

export default function RoleGuard({
  roles,
  children,
}: {
  roles: string[];
  children: React.ReactNode;
}) {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  useEffect(() => {
    const token = document.cookie.match(/access_token=([^;]+)/)?.[1] ?? '';
    setAllowed(hasRole(token, ...roles));
  }, [roles]);
  if (allowed === null) return null;
  if (!allowed) return <p className="p-8 text-red-600">Access denied.</p>;
  return <>{children}</>;
}

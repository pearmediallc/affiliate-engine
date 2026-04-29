'use client';

/**
 * Page-view tracker — POSTs to /audit/track-screen on every route change so
 * the admin audit log shows which screens each user actually visited.
 *
 * Mounted once at the app root. Uses Next.js usePathname() to detect navigation.
 * Failures are silent — tracking never blocks the UI.
 */
import { useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import axios from 'axios';
import { API_BASE_URL } from '@/lib/api';

export function PageTracker() {
  const pathname = usePathname();
  const lastReported = useRef<string | null>(null);
  const lastPath = useRef<string | null>(null);

  useEffect(() => {
    if (!pathname) return;
    // De-dupe: only report on actual change.
    if (lastReported.current === pathname) return;

    const referrer = lastPath.current;
    lastReported.current = pathname;
    lastPath.current = pathname;

    // Fire-and-forget. Anonymous viewers are recorded too (user_id = null).
    axios.post(`${API_BASE_URL}/audit/track-screen`, {
      screen: pathname,
      referrer,
    }).catch(() => {
      // Silent — never disrupt the UX for an audit log call.
    });
  }, [pathname]);

  return null;
}

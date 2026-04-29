import type { Metadata } from 'next';
import '../styles/globals.css';
import { AuthProvider } from '@/lib/auth';
import { PageTracker } from '@/lib/pageTracker';

export const metadata: Metadata = {
  title: 'Affiliate Image Engine',
  description: 'AI-powered ad creative generation platform',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ backgroundColor: '#f5f5f7' }}>
        <AuthProvider>
          <PageTracker />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}

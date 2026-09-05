import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  icons: { icon: '/ratatoskur.svg' },
  title: 'Ratatoskur · Kennaraborð',
  description: 'Verkefnasett, framvinda og úrlausnir nemenda í Ratatoski.',
  robots: { index: false, follow: false },
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="is">
      <body>
        <a className="skip-link" href="#main-content">
          Fara í efni
        </a>
        {children}
      </body>
    </html>
  );
}

import type { LinkPackSnapshot } from '@/lib/link-pack/types';
import { themeStyle } from '@/lib/link-pack/theme-css';
import { imageUrl } from '@/lib/link-pack/api';

export default function LinkPackPage({ snapshot }: { snapshot: LinkPackSnapshot }) {
  const bgUrl = imageUrl(snapshot.background_image_url);
  return (
    <main
      className="lp-root"
      style={{
        ...themeStyle(snapshot.theme),
        minHeight: '100dvh',
        background: 'var(--lp-bg-color)',
        color: 'var(--lp-text-color)',
        fontFamily: 'var(--lp-font), system-ui, sans-serif',
        position: 'relative',
        overflowX: 'hidden',
      }}
    >
      {snapshot.theme.background.type === 'image' && bgUrl && (
        <div
          aria-hidden
          style={{
            position: 'fixed',
            inset: 0,
            backgroundImage: `url(${bgUrl})`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            zIndex: 0,
          }}
        />
      )}
      <div
        style={{
          position: 'relative',
          zIndex: 1,
          maxWidth: 640,
          margin: '0 auto',
          padding: '56px 20px 64px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 16,
        }}
      >
        {/* Avatar, Name, Bio, Items, Social row added in Tasks 17-22 */}
        <div style={{ color: 'var(--lp-text-color)' }}>{snapshot.profile.name}</div>
      </div>
    </main>
  );
}

import {
  Phone, Envelope, InstagramLogo, FacebookLogo, YoutubeLogo, Globe, TiktokLogo, XLogo,
} from '@phosphor-icons/react/dist/ssr';
import type { LinkPackSnapshot } from '@/lib/link-pack/types';

const ICONS = {
  phone: { Icon: Phone, label: 'Call', urlFn: (v: string) => v.startsWith('tel:') ? v : `tel:${v}` },
  email: { Icon: Envelope, label: 'Email', urlFn: (v: string) => v.startsWith('mailto:') ? v : `mailto:${v}` },
  instagram: { Icon: InstagramLogo, label: 'Instagram', urlFn: (v: string) => v.startsWith('http') ? v : `https://instagram.com/${v}` },
  facebook: { Icon: FacebookLogo, label: 'Facebook', urlFn: (v: string) => v.startsWith('http') ? v : `https://facebook.com/${v}` },
  youtube: { Icon: YoutubeLogo, label: 'YouTube', urlFn: (v: string) => v.startsWith('http') ? v : `https://youtube.com/${v}` },
  website: { Icon: Globe, label: 'Website', urlFn: (v: string) => v.startsWith('http') ? v : `https://${v}` },
  tiktok: { Icon: TiktokLogo, label: 'TikTok', urlFn: (v: string) => v.startsWith('http') ? v : `https://tiktok.com/@${v}` },
  x: { Icon: XLogo, label: 'X', urlFn: (v: string) => v.startsWith('http') ? v : `https://x.com/${v}` },
} as const;

const ORDER: (keyof typeof ICONS)[] = ['phone', 'email', 'instagram', 'facebook', 'youtube', 'website', 'tiktok', 'x'];

export default function LinkPackSocialRow({ social }: { social: LinkPackSnapshot['social'] }) {
  const items = ORDER
    .map((k) => ({ key: k, value: social[k] }))
    .filter((x): x is { key: keyof typeof ICONS; value: string } => Boolean(x.value));
  if (items.length === 0) return null;
  return (
    <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 16, flexWrap: 'wrap' }}>
      {items.map(({ key, value }) => {
        const { Icon, label, urlFn } = ICONS[key];
        return (
          <a
            key={key}
            href={urlFn(value)}
            aria-label={label}
            style={{
              color: 'var(--lp-social-color)',
              display: 'grid',
              placeItems: 'center',
              width: 40,
              height: 40,
              borderRadius: '50%',
              border: '1.5px solid var(--lp-social-color)',
              transition: 'background 120ms',
            }}
            target={key === 'phone' || key === 'email' ? undefined : '_blank'}
            rel="noreferrer noopener"
          >
            <Icon size={20} weight="regular" />
          </a>
        );
      })}
    </div>
  );
}

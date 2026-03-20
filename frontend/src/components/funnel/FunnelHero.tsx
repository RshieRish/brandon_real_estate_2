import { ArrowDown, CalendarBlank, CheckCircle } from '@phosphor-icons/react/dist/ssr';
import HalftoneOverlay from '@/components/shared/HalftoneOverlay';

interface FunnelData {
  title: string;
  audience: string;
  event_date: string | null;
  video_url: string | null;
  cta_text: string;
  content: {
    headline?: string;
    subheadline?: string;
    body?: string;
    bullet_points?: string[];
  };
}

interface FunnelHeroProps {
  funnel: FunnelData;
}

function headlineWithGoldLastWord(text: string) {
  const words = text.split(' ');
  if (words.length <= 1) return <span className="text-gold">{text}</span>;
  const last = words.pop()!;
  return (
    <>
      {words.join(' ')}{' '}
      <span className="text-gold" style={{ textShadow: '0 0 40px rgba(234,196,105,0.3)' }}>
        {last}
      </span>
    </>
  );
}

function audienceLabel(audience: string): string {
  const map: Record<string, string> = {
    buyers: 'For Buyers',
    buyer: 'For Buyers',
    sellers: 'For Sellers',
    seller: 'For Sellers',
    investors: 'For Investors',
    investor: 'For Investors',
  };
  return map[audience.toLowerCase()] ?? audience;
}

function isSafeEmbedUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return (
      parsed.hostname === 'www.youtube.com' ||
      parsed.hostname === 'youtube.com' ||
      parsed.hostname === 'player.vimeo.com' ||
      parsed.hostname === 'www.loom.com'
    );
  } catch {
    return false;
  }
}

export default function FunnelHero({ funnel }: FunnelHeroProps) {
  const headline = funnel.content?.headline ?? funnel.title;
  const bulletPoints = funnel.content?.bullet_points;

  return (
    <section className="relative min-h-[100dvh] flex flex-col justify-center overflow-hidden bg-dark-surface">
      {/* Gradient sweep */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(135deg, rgba(10,10,10,1) 0%, rgba(10,10,10,0.92) 60%, rgba(192,130,53,0.08) 100%)',
        }}
        aria-hidden="true"
      />

      <HalftoneOverlay opacity={0.03} />

      {/* Gold left accent bar */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ background: 'linear-gradient(to bottom, transparent, #eac469 30%, #eac469 70%, transparent)' }}
        aria-hidden="true"
      />

      {/* Content */}
      <div className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 pt-24 pb-32 w-full">
        <div className="max-w-3xl">
          {/* Event date badge */}
          {funnel.event_date && (
            <div className="mb-6">
              <span className="inline-flex items-center gap-2 glass border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-4 py-2">
                <CalendarBlank weight="fill" className="w-4 h-4 flex-shrink-0" />
                {new Date(funnel.event_date).toLocaleDateString('en-US', {
                  weekday: 'long',
                  month: 'long',
                  day: 'numeric',
                  year: 'numeric',
                })}
              </span>
            </div>
          )}

          {/* Audience eyebrow */}
          <div className="mb-6">
            <span className="inline-block glass border border-gold/30 text-gold text-xs font-semibold tracking-widest uppercase px-4 py-2">
              {audienceLabel(funnel.audience)}
            </span>
          </div>

          {/* H1 */}
          <h1
            className="font-black text-white leading-tight tracking-tight mb-6"
            style={{ fontSize: 'clamp(2.8rem, 7vw, 5.5rem)' }}
          >
            {headlineWithGoldLastWord(headline)}
          </h1>

          {/* Subheadline */}
          {funnel.content?.subheadline && (
            <p className="text-white/70 text-lg leading-relaxed mb-6 font-light">
              {funnel.content.subheadline}
            </p>
          )}

          {/* Body */}
          {funnel.content?.body && (
            <p className="text-white/50 text-base leading-relaxed mb-6 font-light">
              {funnel.content.body}
            </p>
          )}

          {/* Bullet points */}
          {bulletPoints && bulletPoints.length > 0 && (
            <ul className="space-y-3 mb-6">
              {bulletPoints.map((point, i) => (
                <li key={i} className="flex items-center gap-3">
                  <CheckCircle weight="fill" className="w-5 h-5 text-gold flex-shrink-0" />
                  <span className="text-white/70">{point}</span>
                </li>
              ))}
            </ul>
          )}

          {/* Video embed */}
          {funnel.video_url && isSafeEmbedUrl(funnel.video_url) && (
            <div className="mt-8 max-w-2xl aspect-video relative">
              <iframe
                src={funnel.video_url}
                title={`Video: ${funnel.title}`}
                className="w-full h-full rounded border border-dark-border"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          )}
        </div>
      </div>

      {/* Scroll nudge */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2 pointer-events-none">
        <span className="text-white/30 text-xs tracking-[0.2em] uppercase font-medium">Scroll</span>
        <ArrowDown weight="light" className="w-5 h-5 text-gold/50 animate-bounce" />
      </div>
    </section>
  );
}

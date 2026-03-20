interface HalftoneOverlayProps {
  opacity?: number;
  className?: string;
}

export default function HalftoneOverlay({ opacity = 0.05, className = '' }: HalftoneOverlayProps) {
  return (
    <div
      className={`absolute inset-0 pointer-events-none ${className}`}
      style={{
        backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
        backgroundSize: '20px 20px',
        opacity,
      }}
      aria-hidden="true"
    />
  );
}

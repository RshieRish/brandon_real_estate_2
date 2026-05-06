import { SealCheck } from '@phosphor-icons/react/dist/ssr';

interface Props {
  photoUrl: string | null;
  name: string;
  isVerified: boolean;
}

export default function Avatar({ photoUrl, name, isVerified }: Props) {
  return (
    <div style={{ position: 'relative', width: 96, height: 96 }}>
      <div
        style={{
          width: 96,
          height: 96,
          borderRadius: '50%',
          overflow: 'hidden',
          border: '3px solid #ffffff',
          background: '#1E2330',
          display: 'grid',
          placeItems: 'center',
        }}
      >
        {photoUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={photoUrl} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <span style={{ color: '#fff', fontSize: 28, fontWeight: 700 }}>
            {name?.[0]?.toUpperCase() ?? '?'}
          </span>
        )}
      </div>
      {isVerified && (
        <div
          aria-label="Verified"
          style={{
            position: 'absolute',
            top: -2,
            right: -2,
            width: 28,
            height: 28,
            borderRadius: '50%',
            background: '#fff',
            display: 'grid',
            placeItems: 'center',
          }}
        >
          <SealCheck size={24} weight="fill" color="#2196f3" />
          <span className="sr-only">Verified</span>
        </div>
      )}
    </div>
  );
}

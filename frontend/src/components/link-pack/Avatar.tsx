interface Props {
  photoUrl: string | null;
  name: string;
  isVerified: boolean;
}

export default function Avatar({ photoUrl, name }: Props) {
  return (
    <div style={{ position: 'relative', width: 88, height: 88 }}>
      <div
        style={{
          width: 88,
          height: 88,
          borderRadius: '50%',
          overflow: 'hidden',
          background: '#1E2330',
          display: 'grid',
          placeItems: 'center',
        }}
      >
        {photoUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={photoUrl} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <span style={{ color: '#fff', fontSize: 26, fontWeight: 700 }}>
            {name?.[0]?.toUpperCase() ?? '?'}
          </span>
        )}
      </div>
    </div>
  );
}

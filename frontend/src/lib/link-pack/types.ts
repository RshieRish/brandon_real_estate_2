export type LinkKind = 'classic' | 'thumbnail' | 'group' | 'email_gate';
export type Animation = 'none' | 'pulse' | 'wobble' | 'shake' | 'breathe' | 'bounce';
export type CornerStyle = 'pill' | 'rounded' | 'square';
export type FontFamily = 'Montserrat' | 'Inter' | 'Roboto' | 'Poppins' | 'Playfair Display';

export interface LinkPackTheme {
  background: { type: 'solid' | 'image'; color: string };
  button: { bg: string; text: string; shadow: string; corner: CornerStyle };
  social: { color: string };
  typography: { font: FontFamily; color: string };
}

export interface LinkPackItem {
  id: number;
  kind: LinkKind;
  title: string;
  url: string | null;
  thumbnail_url: string | null;
  gated_filename: string | null;
  gate_modal_headline: string | null;
  gate_modal_subtext: string | null;
  animation: Animation;
  is_active: boolean;
  children: LinkPackItem[];
}

export interface LinkPackSnapshot {
  profile: {
    name: string;
    bio: string;
    photo_url: string | null;
    is_verified: boolean;
  };
  social: {
    phone: string | null;
    email: string | null;
    instagram: string | null;
    facebook: string | null;
    youtube: string | null;
    website: string | null;
    tiktok: string | null;
    x: string | null;
  };
  theme: LinkPackTheme;
  background_image_url: string | null;
  items: LinkPackItem[];
}

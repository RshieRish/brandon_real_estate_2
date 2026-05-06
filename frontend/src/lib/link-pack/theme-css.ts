import type { LinkPackTheme, FontFamily, CornerStyle } from './types';

const CORNER_VALUES: Record<CornerStyle, string> = {
  pill: '9999px',
  rounded: '12px',
  square: '0',
};

const FONT_VARS: Record<FontFamily, string> = {
  'Montserrat': 'var(--font-montserrat)',
  'Inter': 'var(--font-inter)',
  'Roboto': 'var(--font-roboto)',
  'Poppins': 'var(--font-poppins)',
  'Playfair Display': 'var(--font-playfair)',
};

export function themeStyle(theme: LinkPackTheme): React.CSSProperties {
  return {
    ['--lp-bg-color' as any]: theme.background.color,
    ['--lp-btn-bg' as any]: theme.button.bg,
    ['--lp-btn-text' as any]: theme.button.text,
    ['--lp-btn-shadow' as any]: theme.button.shadow,
    ['--lp-btn-radius' as any]: CORNER_VALUES[theme.button.corner],
    ['--lp-social-color' as any]: theme.social.color,
    ['--lp-text-color' as any]: theme.typography.color,
    ['--lp-font' as any]: FONT_VARS[theme.typography.font],
  };
}

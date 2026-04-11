'use client';

import Image from 'next/image';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  FacebookLogo,
  InstagramLogo,
  YoutubeLogo,
  TiktokLogo,
  LinkedinLogo,
} from '@phosphor-icons/react/dist/ssr';

const socialLinks = [
  { icon: FacebookLogo, label: 'Facebook', href: 'https://www.facebook.com/SoldWithSweeneyCo' },
  { icon: InstagramLogo, label: 'Instagram', href: 'https://www.instagram.com/soldwithsweeneyco' },
  { icon: YoutubeLogo, label: 'YouTube', href: 'https://www.youtube.com/@soldwithsweeneyco' },
  { icon: TiktokLogo, label: 'TikTok', href: 'https://www.tiktok.com/@soldwithsweeneyco' },
  { icon: LinkedinLogo, label: 'LinkedIn', href: 'https://www.linkedin.com/in/soldwithsweeneyco/' },
];

const legalLinks = [
  { label: 'Privacy Policy', href: 'https://www.kw.com/kw/privacy-policy.html' },
  { label: 'Terms of Use', href: 'https://www.kw.com/kw/terms-of-use.html' },
  { label: 'DMCA Notice', href: 'https://www.kw.com/kw/dmca.html' },
  { label: 'Accessibility', href: 'https://www.kw.com/kw/accessibility.html' },
];

export default function Footer() {
  return (
    <footer
      className="border-t border-dark-border"
      style={{ backgroundColor: '#0a0a0a' }}
    >
      {/* Main footer grid */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-12 lg:gap-16">

          {/* Column 1: Brand */}
          <div className="flex flex-col gap-6">
            <Image
              src="/logos/sws-primary-white-gold.png"
              alt="Sold With Sweeney & Co."
              width={200}
              height={56}
              className="object-contain object-left h-12 w-auto"
            />
            <p className="text-sm text-gray leading-relaxed max-w-xs">
              Premium real estate representation across Massachusetts &amp; New Hampshire. Driven by integrity, results-obsessed.
            </p>
            <div className="flex items-center gap-3">
              <Image
                src="/logos/KWRS White.png"
                alt="Keller Williams Realty Success"
                width={140}
                height={40}
                className="object-contain h-10 w-auto opacity-70"
              />
            </div>
          </div>

          {/* Column 2: Contact */}
          <div className="flex flex-col gap-5">
            <h3 className="text-xs font-bold tracking-widest uppercase text-gold" style={{ letterSpacing: '0.14em' }}>
              Contact
            </h3>
            <address className="not-italic flex flex-col gap-3 text-sm text-gray leading-relaxed">
              <span className="font-semibold text-white/70">Keller Williams Realty Success</span>
              <span>Satellite: 101 Broadway Rd #21, Dracut, MA 01826</span>
              <span>Main: 138 River Rd, Andover, MA 01810</span>
              <a
                href="tel:+19784752111"
                className="hover:text-gold transition-colors duration-200"
              >
                Office: (978) 475-2111
              </a>
              <a
                href="tel:+19789872806"
                className="hover:text-gold transition-colors duration-200"
              >
                Cell: (978) 987-2806
              </a>
              <a
                href="mailto:info@soldwithsweeney.com"
                className="hover:text-gold transition-colors duration-200 break-all"
              >
                info@soldwithsweeney.com
              </a>
            </address>
            <p className="text-xs text-gray/60 mt-2 leading-relaxed">
              Licensed salesperson in MA &amp; NH with Keller Williams Realty Success
            </p>
          </div>

          {/* Column 3: Connect */}
          <div className="flex flex-col gap-5">
            <h3 className="text-xs font-bold tracking-widest uppercase text-gold" style={{ letterSpacing: '0.14em' }}>
              Connect
            </h3>
            <div className="flex flex-wrap gap-3">
              {socialLinks.map((s) => {
                const Icon = s.icon;
                return (
                  <motion.a
                    key={s.label}
                    href={s.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={s.label}
                    whileHover={{ scale: 1.08 }}
                    whileTap={{ scale: 0.95 }}
                    transition={{ type: 'spring', stiffness: 100, damping: 20 }}
                    className="w-11 h-11 rounded-full border border-dark-border flex items-center justify-center text-gray hover:border-gold hover:text-gold transition-colors duration-200"
                    style={{ backgroundColor: '#111111' }}
                  >
                    <Icon size={20} weight="fill" />
                  </motion.a>
                );
              })}
            </div>
            <p className="text-xs text-gray/60 mt-4 leading-relaxed">
              The Sold With Sweeney &amp; Co. website soldwithsweeney.com is operated by Brandon Sweeney. Powered by Keller Williams Realty Success. All information deemed reliable but not guaranteed.
            </p>
          </div>
        </div>
      </div>

      {/* Legal bar */}
      <div
        className="border-t border-dark-border"
        style={{ backgroundColor: '#070707' }}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-gray/50 text-center sm:text-left">
            &copy; {new Date().getFullYear()} Sold With Sweeney &amp; Co. Brandon Sweeney, REALTOR&reg;. All rights reserved. REALTOR&reg; is a federally registered collective membership mark which identifies a real estate professional who is a member of the National Association of REALTORS&reg; and subscribes to its strict Code of Ethics.
          </p>
          <nav className="flex flex-wrap items-center gap-x-4 gap-y-1 shrink-0">
            {legalLinks.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-gray/40 hover:text-gold/70 transition-colors duration-200 whitespace-nowrap"
              >
                {l.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </footer>
  );
}

'use client';

import Image from 'next/image';
import { motion } from 'framer-motion';
import { InstagramLogo, Play } from '@phosphor-icons/react/dist/ssr';

export interface InstagramPost {
  id: string;
  media_type: string;
  media_url: string;
  thumbnail_url?: string;
  permalink: string;
}

export default function InstagramFeed({ posts = [] }: { posts?: InstagramPost[] }) {
  // fallback if posts empty
  const displayPosts = posts.length > 0 ? posts : [
    { id: '1', media_url: '/frames/frame_010.webp', media_type: 'VIDEO', permalink: 'https://instagram.com/soldwithsweeneyco' },
    { id: '2', media_url: '/frames/frame_020.webp', media_type: 'VIDEO', permalink: 'https://instagram.com/soldwithsweeneyco' },
    { id: '3', media_url: '/frames/frame_030.webp', media_type: 'IMAGE', permalink: 'https://instagram.com/soldwithsweeneyco' },
    { id: '4', media_url: '/frames/frame_040.webp', media_type: 'IMAGE', permalink: 'https://instagram.com/soldwithsweeneyco' },
    { id: '5', media_url: '/frames/frame_050.webp', media_type: 'VIDEO', permalink: 'https://instagram.com/soldwithsweeneyco' },
  ];
  return (
    <section className="bg-[#0a0a0a] py-24 md:py-32 border-t border-dark-border relative overflow-hidden">
      {/* Subtle Dot pattern overlay */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: 'radial-gradient(circle, #eac469 1px, transparent 1px)',
          backgroundSize: '28px 28px',
          opacity: 0.03, // Subtle gold dots matching Giving Back
        }}
        aria-hidden="true"
      />

      <div className="max-w-7xl mx-auto px-6 md:px-12 relative z-10 flex flex-col items-center">
        
        <h2 className="text-white font-black text-3xl md:text-5xl tracking-tight mb-10 text-center">
          The Latest From Instagram
        </h2>

        {/* Profile Info */}
        <div className="flex items-center gap-4 mb-12 self-start md:self-center">
          <div className="relative w-14 h-14 md:w-16 md:h-16 rounded-full overflow-hidden border border-dark-border shrink-0">
            <Image 
              src="/headshots/Brandon Sweeney Headshot Zoomed In.png" 
              alt="Brandon Sweeney" 
              fill 
              className="object-cover"
              sizes="64px"
            />
          </div>
          <div className="text-left">
            <h3 className="text-white font-bold text-base md:text-lg leading-tight mb-1">soldwithsweeneyco</h3>
            <p className="text-white/60 text-xs md:text-sm">Real Estate Agent & Investor | Every move matters</p>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 md:gap-4 lg:gap-6 mb-14 w-full">
          {displayPosts.map((post) => (
            <motion.a
              key={post.id}
              href={post.permalink}
              target="_blank"
              rel="noopener noreferrer"
              className="relative aspect-square bg-dark-card rounded-lg overflow-hidden group border border-dark-border"
              whileHover={{ scale: 1.03 }}
              whileTap={{ scale: 0.98 }}
              transition={{ type: "spring", stiffness: 300, damping: 20 }}
            >
              <Image
                src={post.thumbnail_url || post.media_url}
                alt="Instagram post"
                fill
                className="object-cover opacity-80 group-hover:opacity-100 transition-all duration-300 group-hover:scale-105"
                sizes="(max-width: 768px) 50vw, 20vw"
              />
              {post.media_type === 'VIDEO' && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <Play weight="fill" className="text-white w-10 h-10 md:w-12 md:h-12 opacity-90 drop-shadow-md group-hover:scale-110 transition-transform duration-300" />
                </div>
              )}
            </motion.a>
          ))}
        </div>

        {/* Buttons */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 w-full sm:w-auto">
          <a
            href="https://instagram.com/soldwithsweeneyco"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full sm:w-auto text-center px-8 py-3.5 bg-gold text-[#0a0a0a] font-semibold text-xs md:text-sm tracking-widest uppercase hover:bg-gold-hover transition-colors duration-200 rounded-sm"
          >
            Load More
          </a>
          <a
            href="https://www.instagram.com/soldwithsweeneyco"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full sm:w-auto flex items-center justify-center gap-2.5 px-8 py-3.5 bg-black text-white font-semibold text-xs md:text-sm tracking-widest uppercase border border-dark-border hover:border-white/30 transition-colors duration-200 rounded-sm"
          >
            <InstagramLogo weight="bold" className="w-4 h-4" />
            Follow on Instagram
          </a>
        </div>

      </div>
    </section>
  );
}

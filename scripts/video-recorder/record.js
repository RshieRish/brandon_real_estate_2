const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

async function smoothScroll(page) {
  // Get the total height of the page
  const pageHeight = await page.evaluate(() => document.body.scrollHeight);
  const viewportHeight = await page.evaluate(() => window.innerHeight);
  const scrollSteps = Math.floor(pageHeight / 50); // Scroll 50px at a time
  
  // Wait a moment for initial load animations to finish
  await page.waitForTimeout(3000);

  for (let i = 0; i < scrollSteps; i++) {
    await page.evaluate((step) => {
      window.scrollBy(0, 50);
    }, i);
    // Adjust timeout to control scroll speed (20ms is relatively fast, let's use 30ms for smooth cinematic feel)
    await page.waitForTimeout(30);
  }
  
  // Wait a moment at the bottom
  await page.waitForTimeout(2000);
}

async function recordVideo() {
  // Ensure videos directory exists
  const videoDir = path.join(__dirname, 'videos');
  if (!fs.existsSync(videoDir)) {
    fs.mkdirSync(videoDir);
  }

  console.log('Launching browser...');
  const browser = await chromium.launch({ headless: true });

  const url = 'https://brandon-real-estate-2.vercel.app/';

  // 1. Record Desktop (16:9 4K)
  console.log('Recording Desktop 4K (16:9)...');
  const desktopContext = await browser.newContext({
    viewport: { width: 3840, height: 2160 },
    recordVideo: {
      dir: path.join(videoDir, 'desktop'),
      size: { width: 3840, height: 2160 },
    },
  });
  const desktopPage = await desktopContext.newPage();
  await desktopPage.goto(url, { waitUntil: 'networkidle' });
  await smoothScroll(desktopPage);
  await desktopContext.close();
  console.log('Desktop recording complete.');

  // 2. Record Mobile (9:16 4K)
  console.log('Recording Mobile 4K (9:16)...');
  const mobileContext = await browser.newContext({
    viewport: { width: 2160, height: 3840 },
    isMobile: true,
    hasTouch: true,
    userAgent: 'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36',
    recordVideo: {
      dir: path.join(videoDir, 'mobile'),
      size: { width: 2160, height: 3840 },
    },
  });
  const mobilePage = await mobileContext.newPage();
  await mobilePage.goto(url, { waitUntil: 'networkidle' });
  await smoothScroll(mobilePage);
  await mobileContext.close();
  console.log('Mobile recording complete.');

  await browser.close();
  console.log('All recordings finished! Check the "videos" folder.');
}

recordVideo().catch(console.error);

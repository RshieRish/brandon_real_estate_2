#!/usr/bin/env bash
# Extract 60 frames from house_blast.mp4 for the ExplodingHouseScroll animation.
# Requirements: ffmpeg installed (brew install ffmpeg)
# Source video: frontend/public/assets/house_blast.mp4
set -e

mkdir -p frontend/public/frames
mkdir -p frontend/public/frames/house-blast

echo "Extracting 60 WebP frames (frame_001..frame_060) ..."
ffmpeg -i frontend/public/assets/house_blast.mp4 \
  -vf "fps=12,scale=1920:-2" \
  -frames:v 60 \
  -c:v libwebp \
  -quality 85 \
  frontend/public/frames/frame_%03d.webp

echo "Extracting 60 JPEG frames for component (house-blast/frame_0001..frame_0060) ..."
ffmpeg -i frontend/public/assets/house_blast.mp4 \
  -vf "fps=12,scale=1920:-2" \
  -frames:v 60 \
  -q:v 3 \
  frontend/public/frames/house-blast/frame_%04d.jpg

echo "Done! 60 frames extracted to frontend/public/frames/ and frontend/public/frames/house-blast/"

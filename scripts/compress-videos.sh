#!/usr/bin/env bash
# Compress videos for web delivery
# Requirements: ffmpeg installed
set -e
echo "Compressing aerial_drone_shot.mp4..."
ffmpeg -i frontend/public/assets/aerial_drone_shot.mp4 \
  -c:v libx264 -crf 28 -preset slow \
  -movflags +faststart -an \
  -vf "scale=1920:-2" \
  frontend/public/assets/aerial_drone_shot_compressed.mp4
mv frontend/public/assets/aerial_drone_shot_compressed.mp4 \
   frontend/public/assets/aerial_drone_shot.mp4
echo "Done!"

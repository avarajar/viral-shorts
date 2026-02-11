#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  TikTok Sandbox Demo - Run this while screen recording
# ═══════════════════════════════════════════════════════════
#
#  BEFORE RUNNING:
#  1. Go to TikTok Developer Portal > your app > Sandbox
#  2. Copy the sandbox Client Key and Client Secret
#  3. Paste them below
#  4. Make sure the Redirect URI in the portal matches
#     the one in upload_tiktok.py (https://kanjeo.com/callback)
#     OR update both to: http://localhost:8080/callback
#
# ═══════════════════════════════════════════════════════════

# ──── SANDBOX CREDENTIALS ────
export TIKTOK_CLIENT_KEY="sbawxa5zsa7ap3bt7l"
export TIKTOK_CLIENT_SECRET="t31dZwNf8mNa42372l3CSGAKtc78tb42"

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  VIRAL SHORTS - TikTok Sandbox Demo"
echo "═══════════════════════════════════════════════════"
echo ""

# ──── Step 1: Generate a test video with FFmpeg ────
echo "[1/3] Generating test video..."
TEST_VIDEO="/tmp/viral_shorts_test.mp4"

ffmpeg -y -f lavfi -i "color=c=0x111111:s=1080x1920:d=5:r=30" \
  -c:v libx264 -pix_fmt yuv420p "$TEST_VIDEO" 2>/dev/null

if [ -f "$TEST_VIDEO" ]; then
    SIZE=$(du -h "$TEST_VIDEO" | cut -f1)
    echo "  ✓ Test video created: $TEST_VIDEO ($SIZE)"
else
    echo "  ✗ Failed to create test video"
    exit 1
fi

echo ""

# ──── Step 2: OAuth Authorization ────
echo "[2/3] Starting OAuth authorization..."
echo "  1. A URL will appear. Open it in your browser."
echo "  2. Authorize the app on TikTok."
echo "  3. Copy the FULL URL from the address bar after redirect."
echo "  4. Paste it back here."
echo ""

python3 "$SCRIPTS_DIR/upload_tiktok.py" --auth

if [ $? -ne 0 ]; then
    echo "  ✗ Authorization failed"
    exit 1
fi

echo ""

# ──── Step 3: Upload test video ────
echo "[3/3] Uploading test video to TikTok sandbox..."
echo ""

python3 "$SCRIPTS_DIR/upload_tiktok.py" "$TEST_VIDEO" "Viral Shorts - Sandbox Test #test"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Demo complete!"
echo "═══════════════════════════════════════════════════"
echo ""

# Cleanup
rm -f "$TEST_VIDEO"

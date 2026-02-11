#!/bin/bash
# Setup script for the viral pipeline on Oracle ARM server
set -e

echo "=== Installing system dependencies ==="
sudo apt update -qq
sudo apt install -y -qq ffmpeg python3-pip python3-venv

echo "=== Creating pipeline directories ==="
mkdir -p /home/ubuntu/pipeline/{scripts,clips,audio,output/shorts,templates/music,config}

echo "=== Setting up Python virtual environment ==="
python3 -m venv /home/ubuntu/pipeline/venv
source /home/ubuntu/pipeline/venv/bin/activate

echo "=== Installing Python packages ==="
pip install --quiet --upgrade pip
pip install --quiet edge-tts yt-dlp

echo "=== Verifying installations ==="
echo -n "ffmpeg: " && ffmpeg -version 2>&1 | head -1
echo -n "yt-dlp: " && yt-dlp --version
echo -n "edge-tts: " && edge-tts --version 2>&1 || echo "installed"
echo -n "Python: " && python3 --version

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Set your Groq API key:"
echo "     echo 'export GROQ_API_KEY=your_key_here' >> ~/.bashrc"
echo "     Get a free key at: https://console.groq.com/"
echo ""
echo "  2. (Optional) Add background music:"
echo "     Place .mp3 files in /home/ubuntu/pipeline/templates/music/"
echo ""
echo "  3. Test the pipeline:"
echo "     source /home/ubuntu/pipeline/venv/bin/activate"
echo "     cd /home/ubuntu/pipeline/scripts"
echo "     GROQ_API_KEY=your_key python3 pipeline.py"

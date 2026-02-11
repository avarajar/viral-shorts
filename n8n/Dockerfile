FROM n8nio/n8n:latest
USER root
RUN apk add --no-cache python3 py3-pip ffmpeg bash curl \
    && pip3 install --break-system-packages edge-tts yt-dlp
USER node

#!/bin/bash
# Cleanup all temporary pipeline files
# Called after successful upload or on error

PIPELINE_DIR="/pipeline"

rm -rf "${PIPELINE_DIR}/clips/"*
rm -rf "${PIPELINE_DIR}/audio/"*
rm -rf "${PIPELINE_DIR}/output/tmp/"*

# Keep final outputs for 24h then clean
find "${PIPELINE_DIR}/output" -name "*.mp4" -mmin +1440 -delete 2>/dev/null
find "${PIPELINE_DIR}/output/shorts" -name "*.mp4" -mmin +1440 -delete 2>/dev/null

echo "Cleanup done: $(date)"

#!/bin/bash
# Sets up cron jobs for the put-you-on data pipelines.
# Run this script once on any machine to install the cron jobs.
#
# Expected project location: /Users/ramos/dev/put-you-on
# Expected venv:             /Users/ramos/dev/put-you-on/.venv.pipeline

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$PROJECT_DIR/.venv.pipeline/bin/python3"
LOGS="$PROJECT_DIR/logs"

mkdir -p "$LOGS"

(crontab -l 2>/dev/null | grep -v "put-you-on pipelines\|link_pipeline\|song_pipeline"; cat <<EOF
# put-you-on pipelines
0 0 * * * PYTHONPATH=$PROJECT_DIR $PYTHON -m data_pipeline.link_pipeline.runner >> $LOGS/link_pipeline.log 2>&1
0 4 * * * PYTHONPATH=$PROJECT_DIR $PYTHON -m data_pipeline.song_pipeline.runner >> $LOGS/song_pipeline.log 2>&1
EOF
) | crontab -

echo "Cron jobs installed:"
crontab -l | grep -A2 "put-you-on"

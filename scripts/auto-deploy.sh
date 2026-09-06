#!/bin/bash
# Cron-driven self-deploy for the single-box stack.
#
# GitHub Actions cannot reach this box over SSH (the firewall allows port 22
# from one admin IP only, and Actions egress IPs are unallowlistable Azure
# ranges), so the box polls instead of being pushed to: every 5 minutes cron
# runs this script, which fast-forwards to origin/master and rebuilds only
# when the deployed commit actually moved.
#
# Install: (crontab -l 2>/dev/null; echo "*/5 * * * * $HOME/Stockidence/scripts/auto-deploy.sh >> $HOME/Stockidence/auto-deploy.log 2>&1") | crontab -
#
# State safety: ./data (warehouse) and .env (keys) are untracked, so the
# hard reset below can never clobber them. Logs to auto-deploy.log.
set -euo pipefail

REPO_DIR="$HOME/Stockidence"
LOG="$REPO_DIR/auto-deploy.log"
DOCKER=/usr/bin/docker

log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }

# Skip (quietly) if a previous run is still building.
exec 9>/tmp/stockidence-deploy.lock
flock -n 9 || exit 0

cd "$REPO_DIR"
git fetch -q origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)
if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

log "deploying $REMOTE (was $LOCAL)"
git reset -q --hard origin/master
if "$DOCKER" compose up --build -d >>"$LOG" 2>&1; then
    sleep 20
    # Hit the API container directly: host-level http://localhost/api
    # only proves the nginx redirect, and https needs SNI for the domain.
    if "$DOCKER" compose exec -T api curl -sf http://localhost:8000/api/health >>"$LOG" 2>&1; then
        log "deploy ok"
    else
        log "HEALTH CHECK FAILED after deploy to $REMOTE"
    fi
else
    log "COMPOSE BUILD FAILED for $REMOTE"
fi

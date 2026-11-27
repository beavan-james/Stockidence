#!/bin/bash
# Cron-driven self-deploy for the single-box stack.
#
# GitHub Actions cannot reach this box over SSH (the firewall allows port 22
# from one admin IP only, and Actions egress IPs are unallowlistable Azure
# ranges), so the box polls instead of being pushed to: every 5 minutes cron
# runs this script, which fast-forwards to origin/master and rebuilds only
# when the deployed commit actually moved and the CI workflow
# (.github/workflows/ci.yml) passed for that exact commit.
#
# Install: (crontab -l 2>/dev/null; echo "*/5 * * * * $HOME/Stockidence/scripts/auto-deploy.sh >> $HOME/Stockidence/auto-deploy.log 2>&1") | crontab -
#
# State safety: ./data (warehouse) and .env (keys) are untracked, so the
# hard reset below can never clobber them. Logs to auto-deploy.log.
set -euo pipefail

REPO_DIR="$HOME/Stockidence"
LOG="$REPO_DIR/auto-deploy.log"
# Last commit whose CI failure was logged, so it's logged once, not every run.
CI_LOGGED=/tmp/stockidence-deploy.ci-logged
# Same, for a deploy held back by a Dagster run in progress.
BUSY_LOGGED=/tmp/stockidence-deploy.busy-logged
DOCKER=/usr/bin/docker

log() { echo "[$(date -u +%FT%TZ)] $*" >> "$LOG"; }

if [ -z "${DEPLOY_REMOTE:-}" ]; then
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

    # Deploy only a commit the CI workflow passed. ci_gate.py asks GitHub over
    # HTTPS and prints "<state> <detail>"; anything else (a traceback, no
    # python3) counts as not knowing, so nothing deploys.
    CI=$(python3 "$REPO_DIR/scripts/ci_gate.py" "$REMOTE" 2>&1 | tail -n 1) || true
    case "$CI" in
        "success "*) ;;
        "pending "*)
            # Queued or running: say nothing, the next cron run asks again.
            exit 0
            ;;
        "failed "*)
            # Logged once per commit, though every run re-asks (a re-run of
            # the workflow can still pass).
            if [ "$(cat "$CI_LOGGED" 2>/dev/null)" != "$REMOTE" ]; then
                log "not deploying $REMOTE: ${CI#failed }"
                echo "$REMOTE" > "$CI_LOGGED"
            fi
            exit 0
            ;;
        *)
            REASON=${CI#error }
            log "not deploying $REMOTE: couldn't get its CI result: ${REASON:-no output}"
            exit 0
            ;;
    esac

    # A deploy recreates the Dagster containers and kills any run in flight,
    # so hold it while one is queued or running; the next cron pass retries.
    # Logged once per commit, like the CI failure above.
    BUSY=$(python3 "$REPO_DIR/scripts/dagster_busy.py" 2>&1 | tail -n 1) || true
    case "$BUSY" in
        "idle "*) ;;
        *)
            if [ "$(cat "$BUSY_LOGGED" 2>/dev/null)" != "$REMOTE" ]; then
                log "holding deploy of $REMOTE: ${BUSY:-no output from dagster_busy.py}"
                echo "$REMOTE" > "$BUSY_LOGGED"
            fi
            exit 0
            ;;
    esac

    log "deploying $REMOTE (was $LOCAL)"
    git reset -q --hard origin/master
    # Bash keeps reading the copy of this script it opened, so without this
    # an edit to the deploy steps below would only apply one deploy late.
    # Re-exec the fresh checkout; it inherits fd 9, so the lock stays held.
    DEPLOY_REMOTE="$REMOTE" exec /bin/bash "$REPO_DIR/scripts/auto-deploy.sh"
fi

# Second pass (fresh script): build, restart and health-check.
REMOTE="$DEPLOY_REMOTE"
cd "$REPO_DIR"
if "$DOCKER" compose up --build -d >>"$LOG" 2>&1; then
    sleep 20
    # Hit the API container directly: host-level http://localhost/api
    # only proves the nginx redirect, and https needs SNI for the domain.
    # python:3.12-slim ships no curl, so probe with the image's own Python
    # (urlopen raises on connection errors and non-2xx statuses).
    if "$DOCKER" compose exec -T api python -c \
        "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health', timeout=10).read().decode())" \
        >>"$LOG" 2>&1; then
        log "deploy ok"
        # Every rebuild leaves the previous images dangling plus build
        # cache; on a 50 GB boot volume that fills the disk over many
        # deploys. Only after a healthy deploy, so a rollback target isn't
        # pruned mid-incident; tagged images and recent cache are kept.
        "$DOCKER" image prune -f >>"$LOG" 2>&1 || true
        "$DOCKER" builder prune -f --filter until=168h >>"$LOG" 2>&1 || true
    else
        log "HEALTH CHECK FAILED after deploy to $REMOTE"
    fi
else
    log "COMPOSE BUILD FAILED for $REMOTE"
fi

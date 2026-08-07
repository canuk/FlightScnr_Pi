#!/usr/bin/env bash
# repair-ota.sh — Unblock OTA when local file-mode dirt blocks git pull.
#
# Background: older install-pi.sh ran `chmod 644` on the whole tree and only
# restored +x on install-pi.sh / portal-update.sh. That left scripts/release.sh
# "modified" in git (mode only). The next `git pull --ff-only` then aborts and
# the device stays on the old VERSION (e.g. 2026.8.5.5) even though the portal
# may look like the update "finished".
#
# This script does NOT need a successful pull first — fetch it from GitHub:
#
#   curl -fsSL https://raw.githubusercontent.com/yashmulgaonkar/FlightScnr_Pi/main/scripts/repair-ota.sh | bash
#
# Options:
#   --hard   git fetch + reset --hard origin/main (discards ALL local repo edits),
#            then install --skip-apt. Use if restore alone is not enough.
#   --repo DIR   FlightScnr_Pi checkout path (default: auto-detect)
#
set -euo pipefail

HARD=0
REPO_ROOT="${FLIGHTSCNR_REPO:-}"

while [ $# -gt 0 ]; do
    case "$1" in
        --hard) HARD=1 ;;
        --repo)
            shift
            REPO_ROOT="${1:-}"
            if [ -z "$REPO_ROOT" ]; then
                echo "Missing path for --repo" >&2
                exit 1
            fi
            ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
    shift
done

resolve_repo() {
    local d candidate
    if [ -n "$REPO_ROOT" ] && [ -f "$REPO_ROOT/install-pi.sh" ]; then
        (cd "$REPO_ROOT" && pwd)
        return 0
    fi
    for d in \
        "${HOME:+$HOME/FlightScnr_Pi}" \
        /home/pi/FlightScnr_Pi \
        /home/jason/FlightScnr_Pi \
        "$(pwd)"
    do
        [ -n "$d" ] || continue
        if [ -f "$d/install-pi.sh" ] && [ -d "$d/.git" ]; then
            (cd "$d" && pwd)
            return 0
        fi
    done
    # Last resort: shallow search under /home (typical Pi layouts).
    while IFS= read -r candidate; do
        d="$(dirname "$candidate")"
        if [ -d "$d/.git" ]; then
            (cd "$d" && pwd)
            return 0
        fi
    done < <(find /home -maxdepth 3 -type f -name install-pi.sh 2>/dev/null | head -n 5)
    return 1
}

REPO_ROOT="$(resolve_repo)" || {
    echo "Could not find FlightScnr_Pi (install-pi.sh + .git)." >&2
    echo "Re-run with: bash repair-ota.sh --repo /path/to/FlightScnr_Pi" >&2
    exit 1
}

echo "Repo: $REPO_ROOT"
cd "$REPO_ROOT"

OWNER="$(stat -c '%U' "$REPO_ROOT" 2>/dev/null || echo pi)"
git_safe=(git -c "safe.directory=${REPO_ROOT}" -C "$REPO_ROOT")

run_git() {
    if [ "$(id -u)" -eq 0 ] && [ "$OWNER" != "root" ]; then
        sudo -u "$OWNER" "${git_safe[@]}" "$@"
    else
        "${git_safe[@]}" "$@"
    fi
}

echo "Before: $(run_git status -sb | tr '\n' ' ')"
echo "VERSION=$(tr -d '[:space:]' <VERSION 2>/dev/null || echo '?')"

if [ "$HARD" -eq 1 ]; then
    echo "Hard reset to origin/main (discards local checkout changes)…"
    run_git fetch origin
    # Prefer main; fall back to whatever upstream is.
    if run_git show-ref --verify --quiet refs/remotes/origin/main; then
        run_git reset --hard origin/main
    else
        run_git pull --ff-only || run_git reset --hard '@{u}'
    fi
else
    for rel in scripts/release.sh scripts/release.cmd; do
        if run_git status --porcelain -- "$rel" 2>/dev/null | grep -q .; then
            echo "Clearing local changes: $rel"
            run_git restore --source=HEAD --staged --worktree -- "$rel" 2>/dev/null \
                || run_git checkout HEAD -- "$rel"
        fi
    done
    # If anything else still blocks ff-only, say so clearly.
    if ! run_git diff --quiet || ! run_git diff --cached --quiet; then
        echo "Warning: other local changes still present:" >&2
        run_git status --short >&2
        echo "If pull fails, re-run with --hard" >&2
    fi
fi

echo "After clean: $(run_git status -sb | tr '\n' ' ')"

echo "Running install-pi.sh update…"
if [ "$(id -u)" -eq 0 ]; then
    bash "$REPO_ROOT/install-pi.sh" update
else
    sudo bash "$REPO_ROOT/install-pi.sh" update
fi

echo ""
echo "Done. VERSION=$(tr -d '[:space:]' <VERSION 2>/dev/null || echo '?')"
echo "If the portal still looks old, refresh the page or: sudo systemctl restart flightscnr"
echo "If LightDM switched to X11 for pinch-zoom: sudo reboot"

#!/bin/bash

# Background Re-upload Script for Documents Actually Missing from NEW Qdrant
# Queries actual Qdrant collection instead of trusting progress tracker

set -e

# Configuration
SCRIPT_NAME="reupload_missing_from_qdrant.py"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="reupload_missing_${TIMESTAMP}.log"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║    Re-upload Missing Documents from NEW Qdrant (Verified)  ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check if script exists
if [ ! -f "$SCRIPT_NAME" ]; then
    echo "❌ Error: $SCRIPT_NAME not found"
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found"
    exit 1
fi

# Load environment variables to check configuration
source .env

if [ -z "$NEW_QDRANT_URL" ]; then
    echo "❌ Error: NEW_QDRANT_URL not set in .env"
    echo "   This script requires the NEW Qdrant instance"
    exit 1
else
    echo "✅ NEW_QDRANT_URL: $NEW_QDRANT_URL"
fi

# Find most recent results directory
RESULTS_DIR=""
if [ -d "results" ]; then
    RESULTS_DIR=$(ls -td results/*/ 2>/dev/null | head -1)
    if [ -n "$RESULTS_DIR" ]; then
        echo "✅ Results directory: $RESULTS_DIR"
    else
        echo "❌ Error: No results directories found"
        exit 1
    fi
else
    echo "❌ Error: results/ directory not found"
    exit 1
fi

# Check missing_from_qdrant.txt
if [ -f "missing_from_qdrant.txt" ]; then
    OLD_MISSING_COUNT=$(wc -l < missing_from_qdrant.txt)
    echo "📋 Old missing list (from verify_uploads.py): $OLD_MISSING_COUNT documents"
    echo "   (This script will verify against NEW Qdrant)"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "Re-upload Configuration:"
echo "════════════════════════════════════════════════════════════"
echo "Script:            $SCRIPT_NAME"
echo "Results Directory: $RESULTS_DIR"
echo "Log File:          $LOG_FILE"
echo "Model:             gpt-4.1 (default)"
echo "Batch Delay:       5 seconds"
echo "Qdrant Instance:   NEW (after migration)"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "⚠️  This script will:"
echo "   1. Query NEW Qdrant to find what's ACTUALLY uploaded"
echo "   2. Compare with local CSVs to find truly missing documents"
echo "   3. Re-upload only documents missing from NEW Qdrant"
echo ""

# Confirm execution
read -p "Start re-upload in background mode? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "❌ Re-upload cancelled"
    exit 0
fi

echo ""
echo "🚀 Starting re-upload in background..."
echo ""

# Run in background with auto-confirmation
# Pass "yes" and model name via stdin
echo -e "gpt-4.1\nyes" | nohup python "$SCRIPT_NAME" "${RESULTS_DIR%/}" > "$LOG_FILE" 2>&1 &

PID=$!

echo "✅ Re-upload started with PID: $PID"
echo "📝 Log file: $LOG_FILE"
echo ""
echo "════════════════════════════════════════════════════════════"
echo "Monitoring Commands:"
echo "════════════════════════════════════════════════════════════"
echo "# Live monitoring"
echo "tail -f $LOG_FILE"
echo ""
echo "# Check progress"
echo "grep 'Successfully uploaded' $LOG_FILE | wc -l"
echo ""
echo "# Check for errors"
echo "grep 'Failed to upload' $LOG_FILE"
echo ""
echo "# Check completion"
echo "grep 'Re-upload Summary' $LOG_FILE"
echo ""
echo "# View comparison results"
echo "grep 'Missing from Qdrant:' $LOG_FILE"
echo ""
echo "# Check process status"
echo "ps aux | grep $SCRIPT_NAME"
echo ""
echo "# Kill process if needed"
echo "kill $PID"
echo "════════════════════════════════════════════════════════════"

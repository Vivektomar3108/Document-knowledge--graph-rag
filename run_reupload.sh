#!/bin/bash

# Background Re-upload Script for Failed Documents
# Runs reupload_failed_docs.py in nohup mode

set -e

# Configuration
SCRIPT_NAME="reupload_failed_docs.py"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="reupload_${TIMESTAMP}.log"

echo "╔════════════════════════════════════════════════════════════╗"
echo "║         Re-upload Failed Documents (Background Mode)       ║"
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
    echo "⚠️  Warning: NEW_QDRANT_URL not set in .env"
    echo "   Using old Qdrant instance"
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

# Show missing documents count
PROGRESS_FILE="${RESULTS_DIR}.progress/vectordb_progress.json"
if [ -f "$PROGRESS_FILE" ]; then
    UPLOADED_COUNT=$(grep -o '"completed":' "$PROGRESS_FILE" | wc -l)
    echo "📊 Documents uploaded to vector DB: $UPLOADED_COUNT"
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "Re-upload Configuration:"
echo "════════════════════════════════════════════════════════════"
echo "Results Directory: $RESULTS_DIR"
echo "Log File:          $LOG_FILE"
echo "Model:             gpt-4.1 (default)"
echo "Batch Delay:       5 seconds"
echo "════════════════════════════════════════════════════════════"
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
echo "# Check process status"
echo "ps aux | grep $SCRIPT_NAME"
echo ""
echo "# Kill process if needed"
echo "kill $PID"
echo "════════════════════════════════════════════════════════════"

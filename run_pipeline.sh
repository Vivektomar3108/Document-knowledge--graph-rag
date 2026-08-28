#!/bin/bash

# ============================================================================
# Script to run the XML processing pipeline with nohup
# Enhanced with progress tracking and disk monitoring
# ============================================================================

# Environment variables will be loaded from .env file automatically
# Make sure your .env file contains:
# OPENAI_API_KEY=your_openai_key_here
# LANGCHAIN_API_KEY=your_langchain_key_here
# GOOGLE_API_KEY=your_google_key_here (if using Google)
# QDRANT_URL=your_qdrant_url (if using Qdrant)
# QDRANT_API_KEY=your_qdrant_key (if using Qdrant)
# BACKUP_OPENAI_API_KEY=your_backup_key (optional, for rate limit failover)

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "  Borges Pipeline Launcher with Recovery"
echo "========================================"
echo ""

# Check disk space before starting
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
DISK_FREE=$(df -h / | awk 'NR==2 {print $4}')

echo "📊 Disk Space Check:"
df -h / | grep -E "Filesystem|/dev/root"
echo ""

if [ "$DISK_USAGE" -ge 95 ]; then
    echo -e "${RED}❌ ERROR: Disk usage is ${DISK_USAGE}% (Critical!)${NC}"
    echo "Please free up disk space before running the pipeline."
    echo "Suggestions:"
    echo "  - Remove __pycache__: find . -type d -name '__pycache__' -exec rm -rf {} +"
    echo "  - Remove old logs: rm -f logs/borges_2024-*.log"
    echo "  - Clean temp files: rm -rf temporary_unique_files/*.csv"
    exit 1
elif [ "$DISK_USAGE" -ge 80 ]; then
    echo -e "${YELLOW}⚠️  WARNING: Disk usage is ${DISK_USAGE}% (Monitor closely)${NC}"
    echo "Free space: $DISK_FREE"
    echo ""
else
    echo -e "${GREEN}✅ Disk space OK: ${DISK_USAGE}% used, ${DISK_FREE} free${NC}"
    echo ""
fi

# Check for existing incomplete runs
RESUME_DIR=""
for run_dir in $(ls -t results/ 2>/dev/null); do
    if [ -d "results/$run_dir/.progress" ]; then
        # Check if merging is completed
        if [ -f "results/$run_dir/.progress/merging_progress.json" ]; then
            MERGING_DONE=$(grep -o '"completed": true' "results/$run_dir/.progress/merging_progress.json" 2>/dev/null)
            if [ -n "$MERGING_DONE" ]; then
                continue  # This run is complete, skip it
            fi
        fi

        # Found incomplete run
        RESUME_DIR="results/$run_dir"
        COMPLETED_DOCS=$(grep -o '"total_count": [0-9]*' "$RESUME_DIR/.progress/extraction_progress.json" 2>/dev/null | awk '{print $2}')
        if [ -n "$COMPLETED_DOCS" ]; then
            echo -e "${GREEN}🔄 RESUMING EXISTING RUN: $run_dir${NC}"
            echo -e "${GREEN}📋 Progress: $COMPLETED_DOCS documents already processed${NC}"
            echo "The pipeline will continue from where it left off."
            echo ""
        else
            echo -e "${GREEN}🔄 RESUMING EXISTING RUN: $run_dir${NC}"
            echo "Found incomplete run, will resume processing."
            echo ""
        fi
        break
    fi
done

if [ -z "$RESUME_DIR" ]; then
    echo -e "${GREEN}✨ Starting fresh run${NC}"
    echo ""
fi

# Create a timestamp for the log file
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="pipeline_${TIMESTAMP}.log"

# Activate virtual environment if you're using one
# source /path/to/your/venv/bin/activate

echo "🚀 Starting XML processing pipeline..."
echo "📝 Log file: $LOG_FILE"
echo "⚙️  Process will run in background with nohup"
echo ""
echo "📊 Monitor commands:"
echo "  • Live logs:      tail -f $LOG_FILE"
echo "  • Progress:       tail -f logs/borges_\$(date +%Y-%m-%d).log"
echo "  • Disk space:     watch -n 300 df -h"
echo "  • Stop pipeline:  pkill -f main.py"
echo ""

# Run the pipeline with nohup
# The input responses are piped to the script
nohup python main.py <<EOF > $LOG_FILE 2>&1 &
xml
xmls
openai
gpt-4.1
openai
gpt-4.1-mini
EOF

# Get the process ID
PID=$!
echo "Pipeline started with PID: $PID"
echo "Log file: $LOG_FILE"
echo ""
echo "Useful commands:"
echo "  Monitor logs: tail -f $LOG_FILE"
echo "  Check process: ps aux | grep $PID"
echo "  Kill process: kill $PID"
echo ""
echo "The process is now running in the background."
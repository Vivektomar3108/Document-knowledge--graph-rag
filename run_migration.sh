#!/bin/bash

# ============================================================================
# Run Qdrant migration in background with nohup
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "  Qdrant Migration - Background Mode"
echo "========================================"
echo ""

# Check if .env is configured
if ! grep -q "NEW_QDRANT_URL" .env 2>/dev/null; then
    echo -e "${RED}❌ ERROR: NEW_QDRANT_URL not configured in .env${NC}"
    echo ""
    echo "Add to .env:"
    echo "  NEW_QDRANT_URL=http://107.22.168.201:6333"
    echo "  NEW_QDRANT_API_KEY="
    echo ""
    exit 1
fi

NEW_URL=$(grep "NEW_QDRANT_URL" .env | cut -d= -f2)
echo -e "${GREEN}✅ New Qdrant URL: $NEW_URL${NC}"
echo ""

# Create timestamp for log file
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="migration_${TIMESTAMP}.log"

echo "📝 Log file: $LOG_FILE"
echo ""
echo "⚠️  This will migrate ALL data from old Qdrant to new Qdrant"
echo "   Old: https://af88b374-00e7-4a46-ac96-17bebe98ff08..."
echo "   New: $NEW_URL"
echo ""
echo "Expected time: 30-45 minutes for ~23,000 points"
echo ""

read -p "Continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Migration cancelled."
    exit 0
fi

echo ""
echo "🚀 Starting migration in background..."

# Run migration with automatic "yes" response in background
echo "yes" | nohup python migrate_qdrant.py > $LOG_FILE 2>&1 &

# Get the process ID
PID=$!

echo ""
echo -e "${GREEN}✅ Migration started with PID: $PID${NC}"
echo "📝 Log file: $LOG_FILE"
echo ""
echo "📊 Monitor commands:"
echo "  • Live logs:        tail -f $LOG_FILE"
echo "  • Check progress:   grep 'Migrated' $LOG_FILE | tail -5"
echo "  • Check completion: grep 'Migration Complete' $LOG_FILE"
echo "  • Check process:    ps aux | grep $PID"
echo "  • Kill process:     kill $PID"
echo ""
echo "Expected batches: ~234 batches (100 points each)"
echo ""
echo "The migration is now running in the background."
echo "You can safely close this terminal."

#!/bin/bash
# transfer_to_remote.sh - Transfer updated Lightning DDP files to remote machine
#
# This script transfers the fixed files to the remote test machine:
# 1. Updated job.py (with --work_dir support)
# 2. Updated test_lightning_ddp.sh (uses custom workspace)
# 3. Run guide (optional documentation)
#
# Usage: ./transfer_to_remote.sh

set -e

# Configuration
REMOTE_USER="local-kevlu"
REMOTE_HOST="ipp1-1125"
REMOTE_ADDR="10.117.8.61"
REMOTE_BASE="$REMOTE_USER@$REMOTE_HOST"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Transfer Lightning DDP Files to Remote"
echo "=========================================="
echo ""
echo "Remote: $REMOTE_BASE ($REMOTE_ADDR)"
echo ""

# Get script directory (where this script is located)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"

echo -e "${BLUE}[1/4]${NC} Transferring updated job.py..."
scp "$REPO_ROOT/examples/advanced/multi-gpu/lightning/job.py" \
    "$REMOTE_BASE:~/nvflare_testing/NVFlare/examples/advanced/multi-gpu/lightning/job.py"
echo -e "${GREEN}✓${NC} job.py transferred"
echo ""

echo -e "${BLUE}[2/4]${NC} Transferring test script..."
scp "$SCRIPT_DIR/test_lightning_ddp.sh" \
    "$REMOTE_BASE:~/test_lightning_ddp.sh"
echo -e "${GREEN}✓${NC} test_lightning_ddp.sh transferred"
echo ""

echo -e "${BLUE}[3/4]${NC} Transferring run guide..."
scp "$SCRIPT_DIR/RUN_LIGHTNING_DDP.md" \
    "$REMOTE_BASE:~/RUN_LIGHTNING_DDP.md"
echo -e "${GREEN}✓${NC} RUN_LIGHTNING_DDP.md transferred"
echo ""

echo -e "${BLUE}[4/4]${NC} Making test script executable on remote..."
ssh "$REMOTE_BASE" "chmod +x ~/test_lightning_ddp.sh"
echo -e "${GREEN}✓${NC} Script made executable"
echo ""

echo "=========================================="
echo -e "${GREEN}✓ Transfer Complete!${NC}"
echo "=========================================="
echo ""
echo "Files transferred:"
echo "  1. ~/nvflare_testing/NVFlare/examples/advanced/multi-gpu/lightning/job.py"
echo "  2. ~/test_lightning_ddp.sh"
echo "  3. ~/RUN_LIGHTNING_DDP.md"
echo ""
echo "Next steps:"
echo ""
echo "  # SSH to remote machine"
echo "  ssh $REMOTE_BASE"
echo ""
echo "  # Run test in screen (recommended)"
echo "  screen -S lightning_test"
echo "  ./test_lightning_ddp.sh"
echo "  # Detach: Ctrl-A, then d"
echo ""
echo "  # Or run with nohup"
echo "  nohup ./test_lightning_ddp.sh > lightning_test.log 2>&1 &"
echo ""
echo "  # Monitor progress"
echo "  tail -f ~/nvflare_testing/logs/lightning-ddp_*.log"
echo ""

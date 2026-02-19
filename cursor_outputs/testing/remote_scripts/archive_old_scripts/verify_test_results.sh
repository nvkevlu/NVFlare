#!/bin/bash
# verify_test_results.sh - Verify that tests actually completed successfully
# Usage: ./verify_test_results.sh

echo "=========================================="
echo "Verifying Test Results"
echo "=========================================="
echo ""

WORK_DIR="$HOME/nvflare_testing"
LOG_DIR="$WORK_DIR/logs"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=== PyTorch DDP Test Verification ==="
PYTORCH_LOG=$(ls -t "$LOG_DIR"/multi-gpu-pytorch-ddp_retry_*.log 2>/dev/null | head -1)
if [ -n "$PYTORCH_LOG" ]; then
    echo "Log: $PYTORCH_LOG"
    echo ""
    
    # Check for success indicators
    if grep -q "Finished FedAvg" "$PYTORCH_LOG"; then
        echo -e "${GREEN}✅ Found 'Finished FedAvg' - Training completed${NC}"
    else
        echo -e "${YELLOW}⚠️  'Finished FedAvg' not found${NC}"
    fi
    
    if grep -q "Round [0-9]" "$PYTORCH_LOG"; then
        ROUNDS=$(grep -c "Round [0-9]" "$PYTORCH_LOG")
        echo -e "${GREEN}✅ Found $ROUNDS training rounds${NC}"
    else
        echo -e "${YELLOW}⚠️  No training rounds found${NC}"
    fi
    
    # Check for errors
    if grep -qi "error\|exception\|failed" "$PYTORCH_LOG" | head -5; then
        echo -e "${YELLOW}⚠️  Errors detected in log (may be benign):${NC}"
        grep -i "error\|exception\|failed" "$PYTORCH_LOG" | head -5
    fi
    
    echo ""
    echo "Last 20 lines of PyTorch log:"
    tail -20 "$PYTORCH_LOG"
else
    echo -e "${RED}❌ PyTorch log not found${NC}"
fi

echo ""
echo "=========================================="
echo ""

echo "=== TensorFlow Test Verification ==="
TF_LOG=$(ls -t "$LOG_DIR"/multi-gpu-tensorflow_*.log 2>/dev/null | head -1)
if [ -n "$TF_LOG" ]; then
    echo "Log: $TF_LOG"
    echo ""
    
    # Check for success indicators
    if grep -q "Finished FedAvg\|Result can be found" "$TF_LOG"; then
        echo -e "${GREEN}✅ Found completion message${NC}"
    else
        echo -e "${YELLOW}⚠️  Completion message not found${NC}"
    fi
    
    if grep -q "Epoch\|epoch\|Round" "$TF_LOG"; then
        echo -e "${GREEN}✅ Found training progress${NC}"
    else
        echo -e "${YELLOW}⚠️  No training progress found${NC}"
    fi
    
    # Check duration (should be much longer than 31s)
    LOG_LINES=$(wc -l < "$TF_LOG")
    echo "Log file size: $LOG_LINES lines"
    if [ "$LOG_LINES" -lt 50 ]; then
        echo -e "${YELLOW}⚠️  Log is very short - test may have failed quickly${NC}"
    fi
    
    echo ""
    echo "Last 30 lines of TensorFlow log:"
    tail -30 "$TF_LOG"
else
    echo -e "${RED}❌ TensorFlow log not found${NC}"
fi

echo ""
echo "=========================================="
echo ""

echo "=== Results Directory Check ==="
ls -lh "$WORK_DIR/results/" 2>/dev/null || echo "No results directory"

echo ""
echo "=== Workspace Check ==="
if [ -d "/tmp/nvflare/jobs/workdir" ]; then
    echo "Workspaces created:"
    ls -la /tmp/nvflare/jobs/workdir/
else
    echo "No /tmp/nvflare/jobs/workdir found"
fi

echo ""
echo "=========================================="
echo "Verification Complete"
echo "=========================================="

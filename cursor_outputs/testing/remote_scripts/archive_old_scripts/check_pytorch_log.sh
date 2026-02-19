#!/bin/bash
# check_pytorch_log.sh - Check PyTorch test log for DXO errors
# Usage: ./check_pytorch_log.sh

echo "=========================================="
echo "Checking PyTorch DDP Test Log"
echo "=========================================="
echo ""

PYTORCH_LOG=$(ls -t ~/nvflare_testing/logs/multi-gpu-pytorch-ddp_retry_*.log 2>/dev/null | head -1)

if [ -z "$PYTORCH_LOG" ]; then
    echo "❌ PyTorch log not found"
    exit 1
fi

echo "Log file: $PYTORCH_LOG"
echo ""

# Check for DXO errors
echo "=== Checking for DXO Errors ==="
if grep -q "not a valid DXO" "$PYTORCH_LOG"; then
    echo "⚠️  DXO errors found:"
    grep -n "not a valid DXO" "$PYTORCH_LOG"
    echo ""
    echo "Context (10 lines before/after first error):"
    grep -B 10 -A 10 "not a valid DXO" "$PYTORCH_LOG" | head -30
else
    echo "✅ No DXO errors found"
fi

echo ""
echo "=== Checking for Round Completion ==="
grep -E "Round [0-9]|Finished FedAvg|Accuracy" "$PYTORCH_LOG" | tail -20

echo ""
echo "=== Last 30 Lines ==="
tail -30 "$PYTORCH_LOG"

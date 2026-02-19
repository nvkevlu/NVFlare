# Archive: Old Remote Testing Scripts

This directory contains scripts from the initial remote machine setup and early testing phases.

## Setup Scripts (Initial Environment Setup)
- `verify_env.sh` - Initial environment verification (GPU, CUDA, Python)
- `remote_setup.sh` - Initial NVFlare environment setup script
- `install_cuda.sh` - System-wide CUDA installation (requires sudo)
- `install_cuda_conda.sh` - Conda-based CUDA installation
- `CUDA_INSTALLATION_GUIDE.md` - Guide for CUDA installation options

## One-Time Fix Scripts (Troubleshooting)
- `fix_and_continue.sh` - Fixed `/tmp` space issue during setup
- `resume_tests.sh` - Resumed testing after fixing TMPDIR
- `retry_pytorch_ddp.sh` - Retried PyTorch DDP test after tenseal fix

## Old Test Scripts (Replaced by Specific Tests)
- `run_multi_gpu_tests.sh` - Batch runner for PyTorch DDP and TensorFlow Multi-GPU
- `verify_test_results.sh` - Analyzed logs for test pass/fail
- `check_pytorch_log.sh` - Checked PyTorch test logs

## Status
All scripts in this archive were used during initial setup and troubleshooting phases (Jan 28, 2026).

They are kept for reference but are not needed for current testing.

## Current Active Scripts (Parent Directory)
- `test_lightning_ddp.sh` - PyTorch Lightning DDP test
- `test_tensor_stream.sh` - Tensor streaming LLM test
- `RUN_TENSOR_STREAM.md` - Tensor streaming test guide
- `README.md` - Main testing documentation

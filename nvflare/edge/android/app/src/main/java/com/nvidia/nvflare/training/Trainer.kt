package com.nvidia.nvflare.training

interface Trainer {
    suspend fun train(): FloatArray
} 
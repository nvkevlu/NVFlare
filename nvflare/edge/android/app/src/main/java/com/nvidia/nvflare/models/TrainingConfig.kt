package com.nvidia.nvflare.models

data class TrainingConfig(
    val method: String = "",
    val epochs: Int = 1,
    val batchSize: Int = 32,
    val learningRate: Float = 0.001f,
    val momentum: Float = 0.9f,
    val weightDecay: Float = 0.0001f
) 
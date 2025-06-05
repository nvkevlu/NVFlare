package com.nvidia.nvflare.trainer

import android.util.Log
import com.nvidia.nvflare.models.TrainingConfig
import com.nvidia.nvflare.models.ModelBufferType
import com.nvidia.nvflare.models.ModelNativeFormat
import com.nvidia.nvflare.models.ModelEncoding
import com.nvidia.nvflare.models.ModelExchangeFormat

class ETTrainerWrapper(
    private val modelData: String,
    private val config: TrainingConfig
) : Trainer {
    private val TAG = "ETTrainerWrapper"
    private val trainer = ETTrainer(modelData, config)

    override fun train(config: TrainingConfig): Map<String, FloatArray> {
        Log.d(TAG, "Starting training with config: $config")
        return trainer.train(config)
    }
} 
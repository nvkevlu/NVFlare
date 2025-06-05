package com.nvidia.nvflare.training

import android.util.Log
import com.nvidia.nvflare.models.TrainingConfig
import com.nvidia.nvflare.trainer.ETTrainer

class ETTrainerWrapper : Trainer {
    private val TAG = "ETTrainerWrapper"
    private val trainer: ETTrainer

    constructor(modelBase64: String, config: TrainingConfig) {
        Log.d(TAG, "Initializing with model and config")
        trainer = ETTrainer()
        
        if (!trainer.loadDataset(config.dataSetType)) {
            throw RuntimeException("Failed to load dataset")
        }
        
        if (!trainer.loadModel(modelBase64)) {
            throw RuntimeException("Failed to load model")
        }
        
        Log.d(TAG, "Initialization complete")
    }

    override suspend fun train(): Map<String, FloatArray> {
        Log.d(TAG, "Starting train()")
        val result = trainer.train(TrainingConfig())
        Log.d(TAG, "train() completed with result keys: ${result.keys}")
        return result
    }
} 
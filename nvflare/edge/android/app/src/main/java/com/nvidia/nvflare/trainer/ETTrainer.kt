package com.nvidia.nvflare.trainer

import android.util.Log
import com.nvidia.nvflare.models.TrainingConfig
import com.nvidia.nvflare.models.ModelBufferType
import com.nvidia.nvflare.models.ModelNativeFormat
import com.nvidia.nvflare.models.ModelEncoding
import com.nvidia.nvflare.models.ModelExchangeFormat
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.Base64

class ETTrainer(private val modelData: String, private val config: TrainingConfig) {
    private val TAG = "ETTrainer"

    init {
        System.loadLibrary("executorch_training")
    }

    private external fun nativeTrain(
        modelData: String,
        method: String,
        epochs: Int,
        batchSize: Int,
        learningRate: Float,
        momentum: Float,
        weightDecay: Float
    ): ByteArray

    fun train(config: TrainingConfig): Map<String, FloatArray> {
        Log.d(TAG, "Starting training with config: $config")
        
        // Decode base64 model data
        val decodedModelData = Base64.getDecoder().decode(modelData)
        
        val result = nativeTrain(
            modelData = String(decodedModelData),
            method = config.method,
            epochs = config.totalEpochs,
            batchSize = config.batchSize,
            learningRate = config.learningRate,
            momentum = 0.0f,  // Default momentum
            weightDecay = 0.0f  // Default weight decay
        )

        return deserializeWeightDiff(result)
    }

    private fun deserializeWeightDiff(data: ByteArray): Map<String, FloatArray> {
        val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        val numTensors = buffer.int
        val result = mutableMapOf<String, FloatArray>()

        for (i in 0 until numTensors) {
            val nameLength = buffer.int
            val nameBytes = ByteArray(nameLength)
            buffer.get(nameBytes)
            val name = String(nameBytes)

            val dataLength = buffer.int
            val tensorData = FloatArray(dataLength)
            for (j in 0 until dataLength) {
                tensorData[j] = buffer.float
            }

            result[name] = tensorData
        }

        return result
    }
} 
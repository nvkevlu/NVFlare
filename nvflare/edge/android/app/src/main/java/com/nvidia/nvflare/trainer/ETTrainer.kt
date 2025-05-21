package com.nvidia.nvflare.trainer

class ETTrainer {
    private external fun createTrainer(): Long
    private external fun loadDataset(trainerPtr: Long, datasetType: String): Boolean
    private external fun loadModel(trainerPtr: Long, modelPath: String): Boolean
    private external fun train(trainerPtr: Long, epochs: Int, learningRate: Float)
    private external fun destroyTrainer(trainerPtr: Long)

    private var trainerPtr: Long = 0

    init {
        System.loadLibrary("ettrainer")
        trainerPtr = createTrainer()
    }

    fun loadDataset(datasetType: String): Boolean {
        return loadDataset(trainerPtr, datasetType)
    }

    fun loadModel(modelPath: String): Boolean {
        return loadModel(trainerPtr, modelPath)
    }

    fun train(epochs: Int, learningRate: Float) {
        train(trainerPtr, epochs, learningRate)
    }

    protected fun finalize() {
        destroyTrainer(trainerPtr)
    }
} 
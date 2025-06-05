package com.nvidia.nvflare.training

import android.util.Log
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.nvidia.nvflare.connection.Connection
import com.nvidia.nvflare.models.*
import kotlinx.coroutines.launch

enum class TrainerType {
    EXECUTORCH
}

enum class MethodType(val displayName: String) {
    CNN("cnn"),
    XOR("xor");

    val requiredDataset: String
        get() = when (this) {
            CNN -> "cifar10"
            XOR -> "xor"
        }
}

enum class TrainingStatus {
    IDLE,
    TRAINING,
    STOPPING,
    ERROR
}

class TrainerController(private val connection: Connection) : ViewModel() {
    private val TAG = "TrainerController"
    private val _status = MutableLiveData<TrainingStatus>(TrainingStatus.IDLE)
    val status: LiveData<TrainingStatus> = _status

    private val _trainerType = MutableLiveData<TrainerType>(TrainerType.EXECUTORCH)
    val trainerType: LiveData<TrainerType> = _trainerType

    private val _supportedMethods = MutableLiveData<Set<MethodType>>(setOf(MethodType.CNN, MethodType.XOR))
    val supportedMethods: LiveData<Set<MethodType>> = _supportedMethods

    private var currentTask: kotlinx.coroutines.Job? = null
    private var currentJob: Job? = null

    val capabilities: Map<String, Any>
        get() = mapOf(
            "methods" to _supportedMethods.value?.map { it.name.lowercase() } ?: emptyList()
        )

    init {
        // Set initial capabilities
        connection.setCapabilities(capabilities)
    }

    fun toggleMethod(method: MethodType) {
        val currentMethods = _supportedMethods.value ?: emptySet()
        _supportedMethods.value = if (currentMethods.contains(method)) {
            currentMethods - method
        } else {
            currentMethods + method
        }
        connection.setCapabilities(capabilities)
    }

    fun startTraining() {
        if (_status.value == TrainingStatus.TRAINING) {
            Log.w(TAG, "Training already in progress")
            return
        }

        _status.value = TrainingStatus.TRAINING
        currentTask = viewModelScope.launch {
            try {
                runTrainingLoop()
            } catch (e: Exception) {
                Log.e(TAG, "Training failed", e)
                if (_status.value != TrainingStatus.STOPPING) {
                    _status.value = TrainingStatus.ERROR
                }
            }
        }
    }

    fun stopTraining() {
        _status.value = TrainingStatus.STOPPING
        currentTask?.cancel()
        currentTask = null
        _status.value = TrainingStatus.IDLE
        connection.resetCookie()
    }

    private suspend fun runTrainingLoop() {
        while (true) {
            try {
                // Fetch job
                val jobResponse = connection.fetchJob()
                Log.d(TAG, "Job response: $jobResponse")

                // Check if server requested stop
                if (jobResponse.status == "stopped") {
                    throw NVFlareError.SERVER_REQUESTED_STOP
                }

                // Verify we support this job's method
                val methodString = jobResponse.method ?: ""
                val method = MethodType.values().find { it.name.equals(methodString, ignoreCase = true) }
                if (method == null || !_supportedMethods.value!!.contains(method)) {
                    Log.e(TAG, "Unsupported method: $methodString")
                    throw NVFlareError.INVALID_METADATA("Unsupported method: $methodString")
                }

                currentJob = jobResponse.toJob()

                // Fetch task
                val taskResponse = connection.fetchTask(currentJob!!.id)
                Log.d(TAG, "Task response: $taskResponse")

                // Check if we should continue training
                if (!taskResponse.taskStatus.shouldContinueTraining) {
                    Log.d(TAG, "Training finished - no more tasks")
                    return
                }

                // Create trainer
                val task = taskResponse.toTrainingTask(currentJob!!.id)
                val trainer = createTrainer(task.modelData, task.trainingConfig)

                // Train and get weight differences
                val weightDiff = trainer.train(task.trainingConfig)

                // Send results
                connection.sendResult(
                    jobId = currentJob!!.id,
                    taskId = task.id,
                    taskName = task.name,
                    weightDiff = weightDiff
                )

            } catch (e: Exception) {
                Log.e(TAG, "Error in training loop", e)
                throw e
            }
        }
    }

    private fun createTrainer(modelData: String, config: TrainingConfig): Trainer {
        // Get the method from the config
        val methodString = config.method ?: ""
        val method = MethodType.values().find { it.name.equals(methodString, ignoreCase = true) }
            ?: throw NVFlareError.INVALID_METADATA("Missing or invalid method in config")

        // Verify that we support this method
        if (!_supportedMethods.value!!.contains(method)) {
            throw NVFlareError.INVALID_METADATA("Method $methodString is not supported by this client")
        }

        return when (_trainerType.value) {
            TrainerType.EXECUTORCH -> ETTrainerWrapper(modelData, config)
            else -> throw IllegalStateException("Unsupported trainer type")
        }
    }
} 
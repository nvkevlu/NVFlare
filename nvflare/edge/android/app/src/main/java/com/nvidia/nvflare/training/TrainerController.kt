package com.nvidia.nvflare.training

import com.nvidia.nvflare.connection.Connection
import com.nvidia.nvflare.models.Job
import com.nvidia.nvflare.models.JobMeta
import com.nvidia.nvflare.models.NVFlareError
import com.nvidia.nvflare.models.toJob
import com.nvidia.nvflare.models.toTrainingTask
import kotlinx.coroutines.Job as CoroutineJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers

class TrainerController(
    private val connection: Connection,
    private val deviceStateMonitor: DeviceStateMonitor
) {
    var status: TrainingStatus = TrainingStatus.IDLE
    var trainerType: TrainerType = TrainerType.EXECUTORCH
    var supportedMethods: Set<MethodType> = setOf(MethodType.CIFAR10, MethodType.XOR)
    
    private var currentTask: CoroutineJob? = null
    
    val capabilities: Map<String, Any>
        get() = mapOf(
            "methods" to supportedMethods.map { it.name.lowercase() }
        )
    
    init {
        connection.setCapabilities(capabilities)
    }
    
    fun toggleMethod(method: MethodType) {
        if (supportedMethods.contains(method)) {
            supportedMethods = supportedMethods - method
        } else {
            supportedMethods = supportedMethods + method
        }
        connection.setCapabilities(capabilities)
    }
    
    suspend fun startTraining() {
        if (status != TrainingStatus.IDLE) return
        status = TrainingStatus.TRAINING
        
        currentTask = kotlinx.coroutines.GlobalScope.launch {
            try {
                runTrainingLoop()
            } catch (e: Exception) {
                println("Training error: $e")
                status = TrainingStatus.IDLE
                // Don't rethrow the exception, just log it
            }
        }
        
        try {
            currentTask?.join()
        } catch (e: Exception) {
            println("Task join error: $e")
            status = TrainingStatus.IDLE
            // Don't rethrow the exception, just log it
        }
    }
    
    fun stopTraining() {
        status = TrainingStatus.STOPPING
        currentTask?.cancel()
        currentTask = null
        status = TrainingStatus.IDLE
    }
    
    private suspend fun runTrainingLoop() {
        var currentJob: Job? = null
        var retryCount = 0
        val maxRetries = Int.MAX_VALUE  // Effectively infinite retries
        
        while (currentJob == null && currentTask?.isActive == true && retryCount < maxRetries) {
            try {
                println("Attempting to fetch job (attempt ${retryCount + 1})...")
                val jobResponse = connection.fetchJob()
                
                if (jobResponse.status == "stopped") {
                    println("Server requested stop")
                    status = TrainingStatus.IDLE
                    return
                }
                
                val job = jobResponse.toJob()
                val methodString = job.meta.method ?: ""
                
                if (MethodType.values().any { it.name.lowercase() == methodString } &&
                    supportedMethods.any { it.name.lowercase() == methodString }) {
                    println("Found compatible job: ${job.id} with method: $methodString")
                    currentJob = job
                } else {
                    println("Skipping job with unsupported or missing method: $methodString")
                    println("Supported methods: ${supportedMethods.map { it.name.lowercase() }}")
                    delay(5000)  // Wait 5 seconds before next attempt
                    retryCount++
                    continue
                }
            } catch (e: Exception) {
                println("Failed to fetch job (attempt ${retryCount + 1}): $e")
                println("Retrying in 5 seconds...")
                delay(5000)
                retryCount++
                continue
            }
        }
        
        if (retryCount >= maxRetries) {
            println("Reached maximum retry attempts, but will continue trying...")
            retryCount = 0  // Reset counter and continue
            return
        }
        
        val job = currentJob ?: run {
            println("No job found after all retries")
            status = TrainingStatus.IDLE
            return
        }
        
        while (job.status == "running" && currentTask?.isActive == true) {
            try {
                val taskResponse = connection.fetchTask(job.id)
                
                if (!taskResponse.taskStatus.shouldContinueTraining) {
                    println("Training finished - no more tasks")
                    return
                }
                
                println("task response: $taskResponse")
                val task = taskResponse.toTrainingTask(job.id)
                
                val trainer = createTrainer(task.modelData, job.meta)
                
                // Check device state before training
                if (!deviceStateMonitor.isReadyForTraining) {
                    throw NVFlareError.TRAINING_FAILED("Device not ready")
                }
                
                // Train and get weight differences
                val weightDiff = withContext(Dispatchers.Default) {
                    try {
                        trainer.train()
                    } catch (e: Exception) {
                        println("Training failed: $e")
                        throw e
                    }
                }
                
                // Check device state again before sending results
                if (!deviceStateMonitor.isReadyForTraining) {
                    throw NVFlareError.TRAINING_FAILED("Device no longer ready")
                }
                
                // Send results back
                connection.sendResult(
                    jobId = job.id,
                    taskId = task.id,
                    taskName = task.name,
                    weightDiff = weightDiff
                )
            } catch (e: Exception) {
                println("Task execution failed: $e")
                if (status != TrainingStatus.STOPPING) {
                    status = TrainingStatus.IDLE
                }
                throw e
            }
        }
    }
    
    private fun createTrainer(modelData: Map<String, String>, meta: JobMeta): Trainer {
        val methodString = meta.method ?: ""
        val method = MethodType.values().find { it.name.lowercase() == methodString }
            ?: throw NVFlareError.INVALID_METADATA("Missing or invalid method in job metadata")
        
        if (!supportedMethods.contains(method)) {
            throw NVFlareError.INVALID_METADATA("Method $methodString is not supported by this client")
        }
        
        return when (trainerType) {
            TrainerType.EXECUTORCH -> {
                val modelString = modelData["model_buffer"]
                    ?: throw NVFlareError.INVALID_MODEL_DATA("Missing model_buffer in model data")
                ETTrainerWrapper(modelString, meta)
            }
        }
    }
} 
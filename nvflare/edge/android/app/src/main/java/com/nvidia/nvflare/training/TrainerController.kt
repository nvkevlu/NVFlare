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
                status = TrainingStatus.IDLE
                throw e
            }
        }
        
        currentTask?.join()
    }
    
    fun stopTraining() {
        status = TrainingStatus.STOPPING
        currentTask?.cancel()
        currentTask = null
        status = TrainingStatus.IDLE
    }
    
    private suspend fun runTrainingLoop() {
        var currentJob: Job? = null
        
        while (currentJob == null && currentTask?.isActive == true) {
            try {
                val jobResponse = connection.fetchJob()
                if (jobResponse.status == "stopped") {
                    throw NVFlareError.SERVER_REQUESTED_STOP
                }
                
                val job = jobResponse.toJob()
                val methodString = job.meta.method ?: ""
                if (MethodType.values().any { it.name.lowercase() == methodString } &&
                    supportedMethods.any { it.name.lowercase() == methodString }) {
                    currentJob = job
                } else {
                    println("Skipping job with unsupported or missing method: $methodString")
                    continue
                }
            } catch (e: Exception) {
                println("Failed to fetch job $e, retrying in 5 seconds...")
                delay(5000)
                continue
            }
        }
        
        val job = currentJob ?: throw NVFlareError.JOB_FETCH_FAILED
        
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
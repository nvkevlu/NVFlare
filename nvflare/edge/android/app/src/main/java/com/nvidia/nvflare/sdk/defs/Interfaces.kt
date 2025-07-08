package com.nvidia.nvflare.sdk.defs

/**
 * Interface for data batches used in training.
 */
interface Batch {
    fun getInput(): Any
    fun getLabel(): Any
}

/**
 * Interface for datasets that provide training data.
 */
interface Dataset {
    fun size(): Int
    fun getNextBatch(batchSize: Int): Batch
    fun reset()
}

/**
 * Interface for data sources that provide datasets.
 */
interface DataSource {
    fun getDataset(datasetType: String, ctx: Context): Dataset
}

/**
 * Interface for executors that perform training tasks.
 */
interface Executor {
    fun execute(taskData: DXO, ctx: Context, abortSignal: Signal): DXO
}

/**
 * Interface for filters that transform input/output data.
 */
interface Filter {
    fun filter(data: DXO, ctx: Context, abortSignal: Signal): DXO
}

/**
 * Interface for transforms that modify batches.
 */
interface Transform {
    fun transform(batch: Batch, ctx: Context, abortSignal: Signal): Batch
}

/**
 * Interface for event handlers that respond to training events.
 */
interface EventHandler {
    fun handleEvent(eventType: String, eventData: Any, ctx: Context, abortSignal: Signal)
} 
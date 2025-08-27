# NVFlare Android SDK

The NVFlare Android SDK enables federated learning on Android edge devices, allowing you to participate in collaborative machine learning without sharing raw data.

## Overview

The SDK provides a complete federated learning solution that:
- Connects to NVFlare servers to participate in training rounds
- Executes training tasks using ExecuTorch models
- Manages datasets and training artifacts locally
- Handles all Android-specific implementation details automatically

## Key Components

### Core Classes

- **`AndroidFlareRunner`** - Main orchestrator for federated learning
- **`DataSource`** - Interface for providing training datasets
- **`Dataset`** - Interface for training data access
- **`Connection`** - HTTP communication with NVFlare server

### Training Components

- **`ETTrainer`** - ExecuTorch-specific training implementation
- **`ETTrainerExecutor`** - Executes training tasks
- **`TrainingConfig`** - Training hyperparameters and configuration

## Quick Start

### 1. Add Dependencies

```kotlin
// Add to your app's build.gradle
dependencies {
    implementation project(':nvflare-sdk')
}
```

### 2. Create a Data Source

Implement the `DataSource` interface to provide your training data:

```kotlin
class MyDataSource : DataSource {
    override fun getDataset(datasetType: String, ctx: Context): Dataset {
        return when (datasetType) {
            "xor_et" -> XORDataset()
            "cifar10_et" -> CIFAR10Dataset()
            else -> throw IllegalArgumentException("Unsupported dataset: $datasetType")
        }
    }
}
```

### 3. Start Federated Learning

```kotlin
val runner = AndroidFlareRunner(
    context = context,
    jobName = "xor_et",
    dataSource = MyDataSource(),
    serverHost = "192.168.6.101",
    serverPort = 4321
)

// Start training
runner.run()

// Stop when done
runner.stop()
```

## Supported Models

- **XOR Model** - Simple binary classification for testing
- **CIFAR-10 CNN** - Image classification model
- **Custom Models** - Add your own ExecuTorch models

## Dataset Requirements

Your dataset must implement the `Dataset` interface:

```kotlin
interface Dataset {
    fun size(): Int
    fun getNextBatch(batchSize: Int): Batch?
    fun reset()
    fun setShuffle(shuffle: Boolean)
    fun validate()
}
```

## Configuration

### Training Parameters

Training configuration is handled automatically based on the job type:
- **XOR**: Batch size ≤ 4, optimized for XOR dataset
- **CIFAR-10**: Batch size = 4, optimized for image data

### Server Configuration

- **Host**: NVFlare server IP address or hostname
- **Port**: Server port (default: 4321)
- **Protocol**: HTTP communication

## Error Handling

The SDK provides comprehensive error handling:

```kotlin
try {
    runner.run()
} catch (e: TrainingError) {
    when (e) {
        is TrainingError.DATASET_CREATION_FAILED -> // Handle dataset issues
        is TrainingError.CONNECTION_FAILED -> // Handle network issues
        is TrainingError.TRAINING_FAILED -> // Handle training errors
        is TrainingError.NO_SUPPORTED_JOBS -> // Handle job configuration
    }
}
```

## Logging and Monitoring

The SDK provides detailed logging for:
- Training progress and metrics
- Dataset loading and validation
- Network communication
- Error conditions

Enable debug logging to see detailed information:
```kotlin
Log.d("AndroidFlareRunner", "Training started")
```

## Best Practices

1. **Dataset Management**: Keep strong references to datasets during training
2. **Error Handling**: Always wrap training calls in try-catch blocks
3. **Resource Cleanup**: Call `stop()` when training is complete
4. **Network Configuration**: Use appropriate server host/port for your environment

## Architecture

The SDK follows a layered architecture:
- **App Layer**: Your application code and data sources
- **Runner Layer**: Federated learning orchestration
- **Training Layer**: Model training execution
- **Communication Layer**: Server communication

## Troubleshooting

### Common Issues

- **Dataset not found**: Ensure your DataSource returns valid datasets
- **Connection failed**: Check server host/port and network connectivity
- **Training errors**: Verify model compatibility and dataset format

### Debug Information

Enable debug logging to see:
- Dataset loading details
- Training progress
- Network communication
- Error stack traces

## API Reference

For detailed API documentation, see the individual class files in the SDK package.

## Support

For issues and questions:
1. Check the logs for detailed error information
2. Verify your dataset implementation
3. Ensure server connectivity
4. Review the training configuration

---

**Note**: This SDK is designed for Android edge devices participating in federated learning scenarios. Ensure your use case complies with federated learning best practices and data privacy requirements.

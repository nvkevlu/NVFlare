package com.nvidia.nvflare.ui

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.nvidia.nvflare.connection.Connection
import com.nvidia.nvflare.training.MethodType
import com.nvidia.nvflare.training.TrainerController
import com.nvidia.nvflare.training.TrainingStatus
import com.nvidia.nvflare.training.TrainerType
import com.nvidia.nvflare.training.DeviceStateMonitor
import com.nvidia.nvflare.ui.theme.NVFlareTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            NVFlareTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    MainScreen()
                }
            }
        }
    }
}

@Composable
fun MainScreen() {
    val context = LocalContext.current
    val connection = remember { Connection(context) }
    val trainerController = remember { TrainerController(connection, DeviceStateMonitor(context)) }
    val scope = rememberCoroutineScope()
    
    var hostnameText by remember { mutableStateOf(connection.hostname.value ?: "") }
    var portText by remember { mutableStateOf(connection.port.value?.toString() ?: "") }
    
    // Update connection when text changes
    LaunchedEffect(hostnameText) {
        connection.hostname.value = hostnameText
    }
    LaunchedEffect(portText) {
        connection.port.value = portText.toIntOrNull() ?: 0
    }
    
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        // Hostname and Port Input
        OutlinedTextField(
            value = hostnameText,
            onValueChange = { hostnameText = it },
            label = { Text("Hostname") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true
        )
        
        OutlinedTextField(
            value = portText,
            onValueChange = { portText = it },
            label = { Text("Port") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
            singleLine = true
        )
        
        // Trainer Type Selection
        Text(
            text = "Trainer Type",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(top = 8.dp)
        )
        
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            TrainerType.values().forEach { type ->
                FilterChip(
                    selected = trainerController.trainerType == type,
                    onClick = { trainerController.trainerType = type },
                    label = { Text(type.name) },
                    modifier = Modifier.weight(1f)
                )
            }
        }
        
        // Supported Methods Section
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface
            )
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    text = "Supported Methods",
                    style = MaterialTheme.typography.titleMedium
                )
                
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 200.dp)
                        .verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    MethodType.values().forEach { method ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(method.displayName)
                            Switch(
                                checked = trainerController.supportedMethods.contains(method),
                                onCheckedChange = { trainerController.toggleMethod(method) }
                            )
                        }
                    }
                }
            }
        }
        
        // Training Button
        Button(
            onClick = {
                if (trainerController.status == TrainingStatus.TRAINING) {
                    trainerController.stopTraining()
                } else {
                    scope.launch {
                        trainerController.startTraining()
                    }
                }
            },
            modifier = Modifier.fillMaxWidth(),
            enabled = trainerController.status != TrainingStatus.STOPPING &&
                     trainerController.supportedMethods.isNotEmpty()
        ) {
            Text(
                if (trainerController.status == TrainingStatus.TRAINING) "Stop Training" else "Start Training"
            )
        }
        
        // Progress Indicator
        if (trainerController.status == TrainingStatus.TRAINING) {
            CircularProgressIndicator(
                modifier = Modifier.align(Alignment.CenterHorizontally)
            )
        }
    }
} 
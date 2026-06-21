# Zeepkist AI Project State

## Architecture
- **Mod (C# BepInEx):** Handles telemetry output (UDP 9090) and input injection (UDP 9091).
- **Environment (Python):** `gymnasium` environment (`ZeepkistEnv`) in `scripts/zeep_env.py`.
- **Training:** Stable Baselines3 SAC and PPO in `scripts/train.py`.

## Network Protocol
- **Telemetry (Out):** Binary via UDP 9090. Includes `Position`, `Rotation`, `Velocity`, `AngularVelocity`, `Speed`, `IsSpawned`, `GhostLoaded`, `GhostReady`, `CheckpointReached`, `IsSlipping`, `IsGrounded`, `SurfaceFriction`, `GroundNormal`, `CPDir`, `CPRelPos`, `LevelHash`, and `ResetReason`.
- **Input (In):** Binary via UDP 9091. Header structure `<fffBBi` (18 bytes): `Steering` (-1 to 1 float), `Brake` (0 to 1 float), `ArmsUp` (0 to 1 float), `Reset` (bool), `RequestGhost` (bool), `SpawnIndex` (int).

## C# Mod Details (`Plugin.cs`)
- **Input Handling:** Overrides `InputActionScriptableObject` fields on `New_ControlCar`:
  - `SteerAction2.axis` (continuous float)
  - `BrakeAction2.axis` & `PitchBackwardAction2.axis` (continuous float, `.buttonHeld = Brake > 0.5f`)
  - `ArmsUpAction2.axis` (continuous float, `.buttonHeld = ArmsUp > 0.5f`)
- **Game Speed Control:** Pressing `F10` cycles the timescale through `1.0x`, `1.5x`, `2.0x`, and `3.0x` when AI control is enabled. Disabling AI automatically resets the timescale to `1.0x`.
- **Reset Logic:** Triggers `PlayerManager.Instance.currentMaster.RestartLevel()` and sets `playerCar = null` to signal `IsSpawned: false`.
- **Events:** `RacingApi.WheelBroken`, `Crashed`, and `CrossedFinishLine` set `playerCar = null` and `isRoundActive = false` to trigger reset in Python.
- **Serialization:** Manually maps `Vector3`/`Quaternion` components to avoid "Self referencing loop" errors in `Newtonsoft.Json`.
- **Ghost Visualization:** `GhostVisualizer` uses `LineRenderer` to draw ghost paths.
- **Homing Visualization:** `CheckpointHomingVisualizer` draws a line pointing to the next checkpoint.

## Python Environment (`zeep_env.py`)
- **Observation Space:** 35-dimensional (Simplified 3D Physics-Aware, Eyesight Removed).
  - Includes local velocities, speed, relative ghost position/rotation, ghost speed/flags, ground normal, checkpoint directions, lookahead points (1.5s and 3.0s ahead), steering action, slipping/friction, progress, and groundedness.
- **Reward Function:** 
  - **Progress (Primary):** Reward for reaching new furthest ghost index points (+5.0 per index).
  - **Checkpoint Bonus:** Large reward (+500.0) for crossing checkpoints.
  - **Speed on Path:** Rewards high speed when closely adhering to the ghost path: `vel_local[2] * exp(-dist_to_path * 0.3) * 0.5`. This naturally guides the car back to the path using the smooth exponential gradient of the reward.
  - **Smoothness Penalties:** Momentum decay penalty, swerving/steering-change penalty, air spin penalty, and braking penalties.
- **Groundedness:** Direct boolean `IsGrounded` from telemetry.
- **Stuck Detection:** Resets if `speed < 1.0` for > 5 seconds.
- **Reset Sync:** Double-barrier wait for `IsSpawned` to transition `True -> False` (reset processed) and then `False -> True` (car spawned) to prevent stale socket reads.

## GTR API & Parsing
- **GraphQL:** Endpoint `https://graphql.zeepki.st`. Path: `levels -> records -> recordMedia -> ghostUrl`.
- **Parsing:** `.zeepghost` files are LZMA-compressed. `scripts/parse_ghost.py` uses `lzma` module and robust frame detection (32-byte or 28-byte frames).

## Training Configuration (`train.py`)
- **Indefinite Training:** Runs until manually stopped.
- **Logging:** Enabled TensorBoard logging to `../zeepkist_logs` with wrapper support (`Monitor`) to capture rollout statistics.
- **Graceful Shutdown:** Safe model save on `Ctrl+C`.
- **Normalization:** Uses `VecNormalize` for stable observations/rewards.
- **Health Checks:** Validates model weights for `NaN` on load; backups and recreates if corrupted.
- **TensorBoard:** Fix requires `setuptools < 70` for `pkg_resources` compatibility.


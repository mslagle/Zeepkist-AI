# Zeepkist AI Project State

## Architecture
- **Mod (C# BepInEx):** Handles telemetry output (UDP 9090) and input injection (UDP 9091).
- **Environment (Python):** `gymnasium` environment (`ZeepkistEnv`) in `scripts/zeep_env.py`.
- **Training:** Stable Baselines3 PPO in `scripts/train.py`.

## Network Protocol
- **Telemetry (Out):** JSON via UDP 9090. Includes `Position`, `Rotation`, `Velocity`, `Speed`, `IsSpawned`, `LevelHash`.
- **Input (In):** JSON via UDP 9091. Includes `Steering` (-1 to 1), `Brake` (bool), `ArmsUp` (bool), `Reset` (bool).

## C# Mod Details (`Plugin.cs`)
- **Input Handling:** Overrides `InputActionScriptableObject` fields on `New_ControlCar`:
  - `SteerAction2.axis`
  - `PitchForwardAction2.axis` (mapped from negative acceleration/braking)
  - `PitchBackwardAction2.axis` (mapped from braking)
  - `ArmsUpAction2.axis`
- **Reset Logic:** Triggers `PlayerManager.Instance.currentMaster.RestartLevel()` and sets `playerCar = null` to signal `IsSpawned: false`.
- **Events:** `RacingApi.WheelBroken` sets `playerCar = null` to trigger reset in Python.
- **Serialization:** Manually maps `Vector3`/`Quaternion` components to avoid "Self referencing loop" errors in `Newtonsoft.Json`.
- **Ghost Visualization:** `GhostVisualizer` component uses `LineRenderer` to draw ghost paths (supports uncompressed GTR ghosts).

## Python Environment (`zeep_env.py`)
- **Observation Space:** 110-dimensional (3D Physics-Aware).
  - Includes **75 SphereCasts** (3 layers of 25: Low, Mid, High).
  - Sphere radius **0.75m** ensures clearance detection.
- **Reward Function:** 
  - **Progress (Primary):** Reward for reaching new furthest ghost index points.
  - **Directional Velocity:** Small reward for forward local velocity.
  - **Path Adherence:** Quadratic penalty for distance from ghost path.
  - **Braking Penalty (-2.0):** Applied if grounded and GTR ghost is not braking.
  - **3D Obstacle Avoidance:** Penalizes proximity to walls/boulders across all 3 vision layers.
- **Groundedness:** Detected via `SurfaceFriction > 0.1` (Mod reports 0.0 when airborne).
- **Stuck Detection:** Resets if `speed < 1.0` for > 5 seconds.
- **Reset Sync:** Waits for `IsSpawned` to transition `True -> False -> True` to ensure clean starts.

## GTR API & Parsing
- **GraphQL:** Endpoint `https://graphql.zeepki.st`. Path: `levels -> records -> recordMedia -> ghostUrl`.
- **Parsing:** `.zeepghost` files are LZMA-compressed. `scripts/parse_ghost.py` uses `lzma` module and robust frame detection (32-byte or 28-byte frames).

## Training Configuration (`train.py`)
- **Indefinite Training:** Runs until manually stopped.
- **Normalization:** Uses `VecNormalize` for stable observations/rewards.
- **Health Checks:** Validates model weights for `NaN` on load; backups and recreates if corrupted.
- **TensorBoard:** Fix requires `setuptools < 70` for `pkg_resources` compatibility.

## Pending / Future Work
- Visualizer support for LZMA compressed ghosts in C#.
- Advanced reward shaping for air-time/pitch control.
- Evaluation scripts for testing saved models.

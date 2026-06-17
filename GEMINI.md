# Zeepkist AI Project State

## Architecture
- **Mod (C# BepInEx):** Handles telemetry output (UDP 9090) and input injection (UDP 9091).
- **Environment (Python):** `gymnasium` environment (`ZeepkistEnv`) in `scripts/zeep_env.py`.
- **Training:** Stable Baselines3 PPO in `scripts/train.py`.

## Network Protocol
- **Telemetry (Out):** JSON via UDP 9090. Includes `Position`, `Rotation`, `Velocity`, `Speed`, `IsSpawned`, `LevelHash`, and `IsGrounded` (direct boolean).
- **Input (In):** Binary via UDP 9091. Header structure `<fffBB` (14 bytes): `Steering` (-1 to 1 float), `Brake` (0 to 1 float), `ArmsUp` (0 to 1 float), `Reset` (bool), `RequestGhost` (bool).

## C# Mod Details (`Plugin.cs`)
- **Input Handling:** Overrides `InputActionScriptableObject` fields on `New_ControlCar`:
  - `SteerAction2.axis` (continuous float)
  - `BrakeAction2.axis` & `PitchBackwardAction2.axis` (continuous float, `.buttonHeld = Brake > 0.5f`)
  - `ArmsUpAction2.axis` (continuous float, `.buttonHeld = ArmsUp > 0.5f`)
- **Game Speed Control:** Pressing `F10` cycles the timescale through `1.0x`, `1.5x`, `2.0x`, and `3.0x` when AI control is enabled. Disabling AI automatically resets the timescale to `1.0x`.
- **Reset Logic:** Triggers `PlayerManager.Instance.currentMaster.RestartLevel()` and sets `playerCar = null` to signal `IsSpawned: false`.
- **Events:** `RacingApi.WheelBroken` sets `playerCar = null` to trigger reset in Python.
- **Serialization:** Manually maps `Vector3`/`Quaternion` components to avoid "Self referencing loop" errors in `Newtonsoft.Json`.
- **Ghost Visualization:** `GhostVisualizer` uses `LineRenderer` to draw ghost paths.
- **Raycast Visualization:** `RaycastVisualizer` uses the built-in `Sprites/Default` shader at `15cm` width and `0.8` opacity to draw 75 physics rays in real-time.

## Python Environment (`zeep_env.py`)
- **Observation Space:** 110-dimensional (3D Physics-Aware).
  - Includes **75 SphereCasts** (3 layers of 25: Low, Mid, High).
  - Sphere radius **0.75m** ensures clearance detection.
  - **Local transforms:** `AngularVelocity` is rotated to the car's local frame; `rel_ghost_rot` is computed as the relative quaternion to the ghost (re-establishing translation/rotation invariance).
- **Reward Function:** 
  - **Progress (Primary):** Reward for reaching new furthest ghost index points.
  - **Directional Velocity:** Small reward for forward local velocity.
  - **Capped Path Adherence:** Linear penalty (`-0.1 * dist_to_path`) capped at `-1.5` per step, allowing shortcuts (cheeses) and preventing path-following from dominating training.
  - **Ground Braking Penalty:** Continuous penalty proportional to brake input (`-5.0 * brake`) when grounded, except when the ghost is braking (`-0.1 * brake`).
  - **Air Braking Penalty:** Continuous penalty proportional to brake input only if the car is stable (`-1.0 * brake * max(0, 1 - ||angular_velocity||)`).
  - **Air Spin Penalty:** Penalizes high angular velocity in the air (`-0.05 * ||angular_velocity||`) to incentivize using the brake to stabilize.
- **Groundedness:** Direct boolean `IsGrounded` from telemetry.
- **Stuck Detection:** Resets if `speed < 1.0` for > 5 seconds.
- **Reset Sync:** Waits for `IsSpawned` to transition `True -> False -> True` to ensure clean starts.

## GTR API & Parsing
- **GraphQL:** Endpoint `https://graphql.zeepki.st`. Path: `levels -> records -> recordMedia -> ghostUrl`.
- **Parsing:** `.zeepghost` files are LZMA-compressed. `scripts/parse_ghost.py` uses `lzma` module and robust frame detection (32-byte or 28-byte frames).

## Training Configuration (`train.py`)
- **Indefinite Training:** Runs until manually stopped.
- **Logging:** Enabled TensorBoard logging to `../zeepkist_logs` with wrapper support (`Monitor`) to capture rollout statistics (`ep_rew_mean`, `ep_len_mean`).
- **Graceful Shutdown:** Fixed bare `except:` blocks so pressing `Ctrl+C` instantly triggers a safe model save.
- **Normalization:** Uses `VecNormalize` for stable observations/rewards.
- **Health Checks:** Validates model weights for `NaN` on load; backups and recreates if corrupted.
- **TensorBoard:** Fix requires `setuptools < 70` for `pkg_resources` compatibility.

## Pending / Future Work
- Visualizer support for LZMA compressed ghosts in C#.
- Evaluation scripts for testing saved models.

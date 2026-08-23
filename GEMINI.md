# Zeepkist AI Project State

## Architecture
- **Mod (C# BepInEx):** Direct input hooking via Harmony Prefix patches, telemetry streaming (UDP 9090+), ghost points TCP server (9092+), and In-Game Telemetry HUD (`OnGUI`).
- **Environment (Python):** `gymnasium` environment (`ZeepkistEnv`) in `scripts/python/zeep_env.py` with multi-instance support.
- **Training Pipeline:**
  - **Behavioral Cloning (BC) Pre-trainer:** `scripts/python/pretrain_bc.py` for supervised offline pre-training on 50% median GTR ghosts (~60s).
  - **Reinforcement Learning (SAC / CustomPPO):** `scripts/python/train.py` with `SubprocVecEnv` parallel rollout collection (`--instances N`).
- **Automated Launcher:** `scripts/launch_instances.ps1` for launching windowed instances with auto-track loading.

## Network Protocol
- **Telemetry (Out):** Binary via UDP (Default 9090, +10 per instance). Includes `Position`, `Rotation`, `Velocity`, `AngularVelocity`, `Speed`, `IsSpawned`, `GhostLoaded`, `GhostReady`, `CheckpointReached`, `IsSlipping`, `IsGrounded`, `SurfaceFriction`, `GroundNormal`, `CPDir`, `CPRelPos`, `LevelHash`, and `ResetReason`.
- **Input (In):** Binary via UDP (Default 9091, +10 per instance). Header structure `<fffBBi` (18 bytes): `Steering` (-1 to 1 float), `Brake` (0 to 1 float), `ArmsUp` (0 to 1 float), `Reset` (bool), `RequestGhost` (bool), `SpawnIndex` (int).
- **Ghost Data (TCP):** Binary JSON payload on TCP (Default 9092, +10 per instance).

## C# Mod Details (`Plugin.cs`)
- **Direct Input Prefix Patches (Bulletproof Control):**
  - Intercepts `New_ControlCar.GetSteerActionButLimited` via Harmony `Prefix` returning `CurrentInput.Steering` directly, guaranteeing wheel movement.
  - Intercepts `GetBrakeAxis`, `GetBrakeHeld`, `GetArmsUpAxis`, and `GetArmsUpHeld` via `Prefix` overrides.
- **In-Game Visual Telemetry HUD:** Displays real-time AI status (`AI ACTIVE` / `STANDBY`), timescale (`1.0x` - `3.0x`), track name, numeric control values, and live visual steering deflection bar (`[ <===|===O ]`).
- **Game Speed Control:** Pressing `F10` cycles timescale through `1.0x`, `1.5x`, `2.0x`, and `3.0x` when AI is active.
- **Auto-Track Loading & Title Skip:**
  - `-autoTrack <TrackUID>` CLI argument automatically advances past `PressAnyKeyToStartGame` title screen and loads `GameScene` with the target level.
- **Multi-Instance Support:** `-aiPortOffset <offset>` shifts UDP/TCP ports dynamically.
- **Reset Logic:** Triggers `PlayerManager.Instance.currentMaster.RestartLevel()` and clears `playerCar`.

## GTR Client & Baseline Strategy
- **50% Median Ghost Querying:** `GtrClient.cs` pulls the **50th percentile (median) ghost** instead of the #1 record, ensuring the AI learns clean, standard driving lines and avoids exploit/shortcut glitches.

## Training Pipeline (`pretrain_bc.py` & `train.py`)
- **Yosh / TMRL Architecture Inspiration:**
  - Supervised imitation learning (Behavioral Cloning) pretrains the SAC Actor network on median ghost trajectories in ~60s, allowing the car to drive on Step 0.
  - High-throughput off-policy SAC fine-tuning optimizes racing lines and lap times.
- **Multi-Instance Training:** Run `python train.py --instances N` to scale rollout data collection across parallel game instances.


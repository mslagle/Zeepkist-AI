# Zeepkist AI - Future Architecture & Feature Ideas

This document tracks potential enhancements, architectural ideas, and experimental features planned for future updates.

---

## 1. Physics Time Freezing (Time.timeScale = 0f) During Optimization
* **Concept:** Whenever Stable-Baselines3 triggers a policy/value optimization step (PPO.train()), Python sends a pause: True flag (or 	argetTimeScale: 0.0) over UDP to all connected game replicas.
* **Mechanism:**
  1. Mod intercepts the flag and sets Time.timeScale = 0f.
  2. Unity FixedUpdate() freezes completely, preserving all rigidbodies, angular momentum, and wheel trajectories in mid-air/mid-turn.
  3. Update() and UDP receiver threads remain active; HUD displays [AI OPTIMIZING (PAUSED)].
  4. Once backpropagation finishes (~0.3s), Python sends pause: False and the mod restores Time.timeScale = 1.0f (or user-selected training speed), seamlessly continuing the run without wall collisions or lost inputs.

---

## 2. Ghost Run Replay Mod
* **Concept:** A standalone in-game replay viewer using the run recordings saved in scripts/python/runs/<LevelHash>/.
* **Mechanism:**
  * Mod reads recorded JSON trajectories (Position, Rotation, Speed, Steering, Brake, ArmsUp).
  * Spawns ghost visualizer cars or directly animates a replay car along the saved path to visually inspect the AI's progression, apex cuts, and drift angles over training history.

---

## 3. Dynamic Timescale Modulation
* **Concept:** Dynamically adjust Time.timeScale depending on the track section.
* **Mechanism:**
  * Long straightaways and simple straights run at 3.0x speed for faster rollout collection.
  * Technical corners, chicane entries, and jumps dynamically throttle to 1.0x or 1.5x for higher input fidelity and precision steering.

---

## 4. Multi-Instance Asynchronous Rollout Collector (Apex / IMPALA Style)
* **Concept:** Fully decoupled asynchronous rollout workers where game replicas stream transitions to a centralized replay buffer or queue.
* **Mechanism:**
  * Eliminates the vectorized step barrier (SubprocVecEnv) entirely.
  * Replicas never wait on one another; each instance streams observations continuously while the learner model pulls transitions asynchronously.

---

## 5. DAgger & Interactive Expert Interventions
* **Concept:** Dataset Aggregation (DAgger) where a human driver or the 50% median ghost injects corrective inputs whenever the AI's state uncertainty or off-track distance exceeds a threshold.

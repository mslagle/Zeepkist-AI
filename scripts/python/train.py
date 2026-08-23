import sys
import os
import time
import torch
import numpy as np
import argparse
from stable_baselines3 import PPO, SAC
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv, VecNormalize
from stable_baselines3.common.monitor import Monitor
from zeep_env import ZeepkistEnv

# Standard PPO with clean per-instance lifecycle and logging
class ZeepkistPPO(PPO):
    def train(self) -> None:
        print("\n" + "-"*42)
        print("BRAIN UPDATE: Optimizing Neural Network...")
        start_t = time.time()
        super().train()
        print(f"UPDATE COMPLETE: Took {time.time() - start_t:.1f}s")
        print("-"*42 + "\n")

class Logger(object):
    def __init__(self, filename="zeepkist_training.log"):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8")
    def write(self, message):
        self.terminal.write(message); self.log.write(message)
        try:
            self.terminal.flush(); self.log.flush()
        except Exception:
            pass
    def flush(self):
        try:
            self.terminal.flush(); self.log.flush()
        except Exception:
            pass

from stable_baselines3.common.callbacks import BaseCallback

class TelemetryDashboardCallback(BaseCallback):
    def __init__(self, log_path, check_freq=100):
        super().__init__()
        self.log_path = log_path
        self.check_freq = check_freq
        self.start_time = time.time()

    def _on_step(self) -> bool:
        if self.n_calls % self.check_freq == 0:
            ep_info_buf = getattr(self.model, 'ep_info_buffer', [])
            ep_rew_mean = float(np.mean([ep_info['r'] for ep_info in ep_info_buf])) if len(ep_info_buf) > 0 else 0.0
            ep_len_mean = float(np.mean([ep_info['l'] for ep_info in ep_info_buf])) if len(ep_info_buf) > 0 else 0.0
            fps = int(self.num_timesteps / max(1e-3, (time.time() - self.start_time)))
            elapsed = int(time.time() - self.start_time)
            
            block = (
                "---------------------------------\n"
                f"| time/              |          |\n"
                f"|    fps             | {fps:<8} |\n"
                f"|    time_elapsed    | {elapsed:<8} |\n"
                f"|    total_timesteps | {self.num_timesteps:<8} |\n"
                f"| rollout/           |          |\n"
                f"|    ep_len_mean     | {ep_len_mean:<8.1f} |\n"
                f"|    ep_rew_mean     | {ep_rew_mean:<8.2f} |\n"
                "---------------------------------\n"
            )
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(block)
                    f.flush()
            except Exception:
                pass
        return True

import argparse
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv, VecNormalize

USE_CURRICULUM = False # Spawns always at starting grid

def make_env_fn(instance_id):
    def _init():
        return Monitor(ZeepkistEnv(instance_id=instance_id, use_curriculum=False))
    return _init

def train():
    parser = argparse.ArgumentParser(description="Zeepkist AI Training")
    parser.add_argument("--instances", type=int, default=1, help="Number of concurrent game replicas (default: 1)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(script_dir, "..", "zeepkist_logs")
    sys.stdout = Logger(os.path.join(script_dir, "zeepkist_training.log"))
    sys.stderr = sys.stdout

    SAVE_FREQ = 50_000 
    model_path = os.path.join(script_dir, "zeepkist_ai_model")
    stats_path = os.path.join(script_dir, "zeepkist_vec_normalize.pkl")

    print("\n" + "="*50)
    print(f"New Training Session Started (Replicas: {args.instances})")
    print("="*50)

    if args.instances > 1:
        print(f"Creating parallel SubprocVecEnv across {args.instances} game instances...")
        env = SubprocVecEnv([make_env_fn(i) for i in range(args.instances)])
    else:
        env = DummyVecEnv([make_env_fn(0)])

    # Clean up any stale VecNormalize pickle so it does not distort observations
    if os.path.exists(stats_path):
        try: os.remove(stats_path)
        except: pass

    ALGO = "PPO" # PPO prevents off-policy Q-critic policy degeneration
    
    # Collect many full runs before each brain update (4096 steps ~ 8-10 complete laps per replica)
    target_n_steps = 4096
    target_batch_size = 128

    # 2. Define the model
    model = None
    if os.path.exists(model_path + ".zip"):
        print(f"Loading existing {ALGO} model...")
        try:
            if ALGO == "SAC":
                model = SAC.load(model_path, env=env, tensorboard_log=log_dir)
                model.learning_starts = 0  # Pretrained model: use policy immediately without random exploration
            else:
                model = ZeepkistPPO.load(model_path, env=env, tensorboard_log=log_dir)
                model.n_steps = target_n_steps
                model.batch_size = target_batch_size
                # Rebuild buffer to match new observation space and size
                from stable_baselines3.common.buffers import RolloutBuffer
                model.rollout_buffer = RolloutBuffer(model.n_steps, model.observation_space, model.action_space, device=model.device, n_envs=model.n_envs)
            print(f"Model loaded successfully.")
        except Exception as e:
            print(f"Model load failed ({e}), starting fresh.")
            os.rename(model_path + ".zip", f"{model_path}_old_{int(time.time())}.zip")

    if model is None:
        if ALGO == "SAC":
            print("Creating fresh SAC model...")
            model = SAC(
                "MlpPolicy", env, verbose=1,
                learning_rate=3e-4,
                buffer_size=100_000,
                learning_starts=0,
                batch_size=256,
                tau=0.005,
                gamma=0.99,
                ent_coef="auto",
                tensorboard_log=log_dir
            )
        else:
            print("Creating fresh PPO model...")
            model = ZeepkistPPO(
                "MlpPolicy", env, verbose=1,
                learning_rate=3e-4, n_steps=target_n_steps, batch_size=target_batch_size,
                n_epochs=4, gamma=0.99, gae_lambda=0.95, ent_coef=0.01,
                tensorboard_log=log_dir
            )

    checkpoint_callback = CheckpointCallback(save_freq=SAVE_FREQ, save_path=os.path.join(script_dir, "checkpoints"), name_prefix=f"zeep_{ALGO.lower()}")
    dashboard_callback = TelemetryDashboardCallback(os.path.join(script_dir, "zeepkist_training.log"), check_freq=100)

    # 4. Start Learning
    try:
        model.learn(total_timesteps=1_000_000_000, progress_bar=True, callback=[checkpoint_callback, dashboard_callback])
    except KeyboardInterrupt:
        print("\nInterrupt detected! Protecting save process from further interrupts...")
    finally:
        # --- SAVE PROTECTION ---
        # Ignore further Ctrl+C signals so we don't corrupt the model during the write
        import signal
        try:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except Exception:
            pass
        
        print(f"Final save to {model_path}...")
        try:
            model.save(model_path)
            if hasattr(env, "save"):
                env.save(stats_path)
        except Exception as e:
            print(f"Error saving model/stats: {e}")

        try:
            env.close() # This triggers zeep_env.save_time()
        except Exception:
            pass
            
        print("Done. You can now safely close this window.")

if __name__ == "__main__":
    train()

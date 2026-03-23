import sys
import os
import time
import torch
import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from zeep_env import ZeepkistEnv

class CustomPPO(PPO):
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
        self.terminal.flush(); self.log.flush()
    def flush(self):
        self.terminal.flush(); self.log.flush()

def make_env(): return ZeepkistEnv()

def train():
    sys.stdout = Logger("zeepkist_training.log")
    sys.stderr = sys.stdout

    SAVE_FREQ = 50_000 
    model_path = "zeepkist_ai_model"
    stats_path = "zeepkist_vec_normalize.pkl"

    print("\n" + "="*50)
    print("New Physics-Aware Training Session Started")
    print("="*50)

    venv = DummyVecEnv([make_env])
    
    env = None
    if os.path.exists(stats_path):
        print("Loading existing normalization stats...")
        try: env = VecNormalize.load(stats_path, venv)
        except: os.remove(stats_path)

    if env is None:
        print("Creating new normalization stats...")
        env = VecNormalize(venv, norm_obs=True, norm_reward=True, clip_obs=10.0)

    model = None
    if os.path.exists(model_path + ".zip"):
        print("Loading existing model...")
        try:
            model = CustomPPO.load(model_path, env=env)
            model.n_steps = 2048
            model.batch_size = 128
            # Rebuild buffer to match new observation space (48 dims)
            from stable_baselines3.common.buffers import RolloutBuffer
            model.rollout_buffer = RolloutBuffer(model.n_steps, model.observation_space, model.action_space, device=model.device, n_envs=model.n_envs)
        except Exception as e:
            print(f"Model load failed ({e}), starting fresh.")
            os.rename(model_path + ".zip", f"{model_path}_old_{int(time.time())}.zip")

    if model is None:
        print("Creating fresh model for 48-dim physics space...")
        model = CustomPPO(
            "MlpPolicy", env, verbose=1,
            learning_rate=3e-4, n_steps=2048, batch_size=128,
            n_epochs=10, gamma=0.99, gae_lambda=0.95, ent_coef=0.01
        )

    checkpoint_callback = CheckpointCallback(save_freq=SAVE_FREQ, save_path="./checkpoints/", name_prefix="zeep_physics")

    try:
        model.learn(total_timesteps=1_000_000_000, progress_bar=True, callback=[checkpoint_callback])
    except KeyboardInterrupt:
        print("\nSaving progress...")
    finally:
        model.save(model_path)
        env.save(stats_path)
        print("Done.")

if __name__ == "__main__":
    train()

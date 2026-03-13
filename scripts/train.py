import sys
import os
import time
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from zeep_env import ZeepkistEnv

class Logger(object):
    def __init__(self, filename="zeepkist_training.log"):
        self.terminal = sys.stdout
        self.log = open(filename, "a", encoding="utf-8")

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.terminal.flush()
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def make_env():
    return ZeepkistEnv()

def train():
    sys.stdout = Logger("zeepkist_training.log")
    sys.stderr = sys.stdout

    # Constants for indefinite training
    TOTAL_TIMESTEPS = 1_000_000_000 # 1 Billion (Practically infinite)
    SAVE_FREQ = 50_000 # Save checkpoint every ~10-15 mins depending on FPS

    print("\n" + "="*50)
    print("Indefinite Training Session Started")
    print(f"Model will save to ../zeepkist_ai_model every {SAVE_FREQ} steps.")
    print("Press Ctrl+C in this window to stop training safely.")
    print("="*50)

    # 1. Initialize the environment with normalization
    venv = DummyVecEnv([make_env])
    
    stats_path = "../zeepkist_vec_normalize.pkl"
    env = None
    if os.path.exists(stats_path):
        print("Attempting to load existing normalization stats...")
        try:
            # We wrap this in a try-except to catch shape mismatches
            env = VecNormalize.load(stats_path, venv)
            print("Normalization stats loaded successfully.")
        except Exception as e:
            print(f"Normalization stats load failed: {e}. Observation space may have changed.")
            backup_stats = f"../zeepkist_vec_normalize_failed_{int(time.time())}.pkl"
            os.rename(stats_path, backup_stats)
            env = None

    if env is None:
        print("Creating new normalization stats...")
        env = VecNormalize(venv, norm_obs=True, norm_reward=True, clip_obs=10.0)

    model_path = "../zeepkist_ai_model"
    log_dir = "../zeepkist_logs/"
    checkpoint_dir = "../zeepkist_checkpoints/"
    
    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)

    # 2. Define the model
    model = None
    if os.path.exists(model_path + ".zip"):
        print("Attempting to load existing model...")
        try:
            model = PPO.load(model_path, env=env)
            # Weight health check
            for param in model.policy.parameters():
                if torch.isnan(param).any():
                    raise ValueError("Model weights contain NaN")
            print("Model loaded successfully.")
        except Exception as e:
            print(f"Model load failed: {e}. This is likely due to a change in observation/action space.")
            backup_name = f"{model_path}_failed_{int(time.time())}.zip"
            if os.path.exists(model_path + ".zip"):
                os.rename(model_path + ".zip", backup_name)
            model = None

    if model is None:
        print("Creating new model...")
        model = PPO(
            "MlpPolicy", 
            env, 
            verbose=1, 
            tensorboard_log=log_dir,
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01
        )

    # 3. Setup Callbacks
    checkpoint_callback = CheckpointCallback(
        save_freq=SAVE_FREQ,
        save_path=checkpoint_dir,
        name_prefix="zeep_continuous"
    )

    # 4. Start Learning
    try:
        model.learn(
            total_timesteps=TOTAL_TIMESTEPS, 
            progress_bar=True,
            callback=[checkpoint_callback]
        )
        print("Training reached the total timestep limit.")
    except KeyboardInterrupt:
        print("\nTraining interrupted by user. Saving progress...")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Saving final model and stats...")
        model.save(model_path)
        env.save(stats_path)
        env.close()
        print("Cleanup complete.")

if __name__ == "__main__":
    train()

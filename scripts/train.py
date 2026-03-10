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
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

def make_env():
    return ZeepkistEnv()

def train():
    sys.stdout = Logger("zeepkist_training.log")
    sys.stderr = sys.stdout

    print("\n" + "="*50)
    print(f"Training Session Started: {os.path.abspath('zeepkist_training.log')}")
    print("="*50)

    # 1. Initialize the environment with normalization
    # Normalizing observations is crucial for PPO with non-standard ranges
    venv = DummyVecEnv([make_env])
    
    stats_path = "../zeepkist_vec_normalize.pkl"
    if os.path.exists(stats_path):
        print("Loading existing normalization stats...")
        env = VecNormalize.load(stats_path, venv)
    else:
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
            for param in model.policy.parameters():
                if torch.isnan(param).any():
                    raise ValueError("Model weights contain NaN")
            print("Model loaded successfully.")
        except (ValueError, Exception) as e:
            print(f"Model load failed or corrupted: {e}")
            backup_name = f"{model_path}_failed_{int(time.time())}.zip"
            print(f"Backing up corrupted model to {backup_name} and creating new model...")
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
        save_freq=10000,
        save_path=checkpoint_dir,
        name_prefix="zeep_model"
    )

    # 4. Start Learning
    print("Starting training. Please ensure Zeepkist is running and AI is enabled in mod settings.")
    try:
        model.learn(
            total_timesteps=1000000, 
            progress_bar=True,
            callback=checkpoint_callback
        )
        model.save(model_path)
        env.save(stats_path)
        print(f"Model saved to {model_path}")
    except KeyboardInterrupt:
        print("Training interrupted. Saving current progress...")
        model.save(model_path)
        env.save(stats_path)
    except Exception as e:
        print(f"An error occurred during training: {e}")
        import traceback
        traceback.print_exc()
    finally:
        env.close()

if __name__ == "__main__":
    train()

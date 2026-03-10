import sys
import os
import time
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback, BaseCallback
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

class TimedStoppingCallback(BaseCallback):
    """
    Callback that stops training after a certain amount of time.
    """
    def __init__(self, max_seconds: int, verbose=0):
        super(TimedStoppingCallback, self).__init__(verbose)
        self.max_seconds = max_seconds
        self.start_time = None

    def _on_training_start(self) -> None:
        self.start_time = time.time()

    def _on_step(self) -> bool:
        if time.time() - self.start_time > self.max_seconds:
            if self.verbose > 0:
                print(f"Stopping training as max time of {self.max_seconds}s has been reached.")
            return False
        return True

def make_env():
    return ZeepkistEnv()

def train():
    sys.stdout = Logger("zeepkist_training.log")
    sys.stderr = sys.stdout

    # Constants for long-term training
    HOURS = 12
    MAX_SECONDS = HOURS * 3600
    TOTAL_TIMESTEPS = 100_000_000 # High enough to let the timer decide
    SAVE_FREQ = 50_000 # Save checkpoint every ~10-15 mins depending on FPS

    print("\n" + "="*50)
    print(f"Long-term Training Session Started: {HOURS} hours goal")
    print(f"Targeting end time: {time.ctime(time.time() + MAX_SECONDS)}")
    print("="*50)

    # 1. Initialize the environment with normalization
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
            # Weight health check
            for param in model.policy.parameters():
                if torch.isnan(param).any():
                    raise ValueError("Model weights contain NaN")
            print("Model loaded successfully.")
        except Exception as e:
            print(f"Model load failed: {e}")
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
        name_prefix="zeep_long_train"
    )
    
    time_callback = TimedStoppingCallback(max_seconds=MAX_SECONDS, verbose=1)

    # 4. Start Learning
    print(f"Starting learning loop. Model will save to {model_path} every {SAVE_FREQ} steps and on finish.")
    try:
        model.learn(
            total_timesteps=TOTAL_TIMESTEPS, 
            progress_bar=True,
            callback=[checkpoint_callback, time_callback]
        )
        print("Training finished normally.")
    except KeyboardInterrupt:
        print("Training interrupted by user.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
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

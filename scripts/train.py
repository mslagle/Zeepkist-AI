from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from zeep_env import ZeepkistEnv
import os

def train():
    # 1. Initialize the environment
    env = ZeepkistEnv()

    model_path = "../zeepkist_ai_model"
    log_dir = "../zeepkist_logs/"
    checkpoint_dir = "../zeepkist_checkpoints/"
    
    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)

    # 2. Define the model
    if os.path.exists(model_path + ".zip"):
        print("Loading existing model...")
        model = PPO.load(model_path, env=env)
    else:
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
        print(f"Model saved to {model_path}")
    except KeyboardInterrupt:
        print("Training interrupted. Saving current progress...")
        model.save(model_path)
    finally:
        env.close()

if __name__ == "__main__":
    train()

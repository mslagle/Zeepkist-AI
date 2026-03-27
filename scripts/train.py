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
    def collect_rollouts(
        self,
        env: "VecEnv",
        callback: "BaseCallback",
        rollout_buffer: "RolloutBuffer",
        n_rollout_steps: int,
    ) -> bool:
        # Restore absolute max size at the start of a new collection
        rollout_buffer.buffer_size = n_rollout_steps

        # If we forced a reset in the last update, perform the actual wait/reset now.
        if self._last_obs is None:
            self._last_obs = env.reset()

        assert self._last_obs is not None, "No previous observation"
        self.policy.set_training_mode(False)
        n_steps = 0
        rollout_buffer.reset()
        callback.on_rollout_start()

        while n_steps < n_rollout_steps:
            with torch.no_grad():
                obs_tensor = torch.as_tensor(self._last_obs).to(self.device)
                actions, values, log_probs = self.policy(obs_tensor)
            
            new_obs, rewards, dones, infos = env.step(actions.cpu().numpy())
            self.num_timesteps += env.num_envs
            n_steps += 1
            
            rollout_buffer.add(self._last_obs, actions, rewards, dones, values, log_probs)
            self._last_obs = new_obs

            callback.update_child_locals(locals())
            if callback.on_step() is False:
                return False

            # SYNC ON RESET: If car crashed/finished and we have enough data (min 2048), update now.
            if dones[0] and n_steps >= 2048:
                print(f"Episode ended (Step {n_steps}). Starting brain update during reset...")
                # TRICK: Tell SB3 the buffer is full at this exact step count
                rollout_buffer.buffer_size = n_steps
                rollout_buffer.full = True
                break
        
        # --- FORCE-SYNC RESET ---
        # Tell the mod to restart the level NOW so it reloads while we optimize.
        env.envs[0].force_mod_reset()
        # Force the next rollout to call env.reset()
        self._last_obs = None
                
        with torch.no_grad():
            last_values = self.policy.predict_values(torch.as_tensor(new_obs).to(self.device))
            
        rollout_buffer.compute_returns_and_advantage(last_values, dones)
        callback.on_rollout_end()
        return True

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

    # Standardized hyperparameters for stability
    target_n_steps = 16384 # Approx 3-4 minutes of driving
    target_batch_size = 128

    # 2. Define the model
    model = None
    if os.path.exists(model_path + ".zip"):
        print("Loading existing model...")
        try:
            model = CustomPPO.load(model_path, env=env)
            model.n_steps = target_n_steps
            model.batch_size = target_batch_size
            # Rebuild buffer to match new observation space and size
            from stable_baselines3.common.buffers import RolloutBuffer
            model.rollout_buffer = RolloutBuffer(model.n_steps, model.observation_space, model.action_space, device=model.device, n_envs=model.n_envs)
            print(f"Model loaded. Buffer resized to {model.n_steps}")
        except Exception as e:
            print(f"Model load failed ({e}), starting fresh.")
            os.rename(model_path + ".zip", f"{model_path}_old_{int(time.time())}.zip")

    if model is None:
        print("Creating fresh model for 48-dim physics space...")
        model = CustomPPO(
            "MlpPolicy", env, verbose=1,
            learning_rate=3e-4, n_steps=target_n_steps, batch_size=target_batch_size,
            n_epochs=10, gamma=0.99, gae_lambda=0.95, ent_coef=0.01
        )

    checkpoint_callback = CheckpointCallback(save_freq=SAVE_FREQ, save_path="./checkpoints/", name_prefix="zeep_physics")

    # 4. Start Learning
    try:
        model.learn(total_timesteps=1_000_000_000, progress_bar=True, callback=[checkpoint_callback])
    except KeyboardInterrupt:
        print("\nInterrupt detected! Protecting save process from further interrupts...")
    finally:
        # --- SAVE PROTECTION ---
        # Ignore further Ctrl+C signals so we don't corrupt the model during the write
        import signal
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        
        print(f"Final save to {model_path}...")
        model.save(model_path)
        env.save(stats_path)
        env.close() # This now triggers zeep_env.save_time()
        print("Done. You can now safely close this window.")

if __name__ == "__main__":
    train()

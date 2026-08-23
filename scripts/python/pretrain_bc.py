import os
import sys
import json
import time
import socket
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from stable_baselines3 import SAC, PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from zeep_env import ZeepkistEnv

class GhostDataset(Dataset):
    def __init__(self, obs_list, action_list):
        self.obs = torch.tensor(obs_list, dtype=torch.float32)
        self.actions = torch.tensor(action_list, dtype=torch.float32)

    def __len__(self):
        return len(self.obs)

    def __getitem__(self, idx):
        return self.obs[idx], self.actions[idx]

def extract_demonstrations(env, ghost_frames):
    env.ghost_frames = ghost_frames
    
    observations = []
    actions = []
    
    n_frames = len(ghost_frames)
    print(f"Generating augmented demonstration dataset with recovery states from {n_frames} median ghost frames...")
    
    # Offsets in meters relative to the track centerline to teach self-correction
    lateral_offsets = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
    
    for i in range(n_frames - 1):
        f = ghost_frames[i]
        f_next = ghost_frames[i + 1]
        
        pos = np.array(f['p'])
        next_pos = np.array(f_next['p'])
        dt = 0.02
        vel_world = (next_pos - pos) / dt
        
        quat = {'x': f['r'][0], 'y': f['r'][1], 'z': f['r'][2], 'w': f['r'][3]}
        
        # Local Right Vector (World Coordinates)
        qx, qy, qz, qw = quat['x'], quat['y'], quat['z'], quat['w']
        car_right = np.array([
            1.0 - 2.0 * (qy * qy + qz * qz),
            2.0 * (qx * qy + qw * qz),
            2.0 * (qx * qz - qw * qy)
        ])
        
        brake_target = 1.0 if f.get('b', False) else 0.0
        arms_target = 1.0 if f.get('a', False) else 0.0

        for offset in lateral_offsets:
            perturbed_pos = pos + offset * car_right
            
            env.last_telemetry = {
                'Time': i * dt,
                'Position': {'x': perturbed_pos[0], 'y': perturbed_pos[1], 'z': perturbed_pos[2]},
                'Rotation': quat,
                'Velocity': {'x': vel_world[0], 'y': vel_world[1], 'z': vel_world[2]},
                'AngularVelocity': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                'Speed': float(f.get('s', np.linalg.norm(vel_world))),
                'IsSpawned': True,
                'IsSlipping': False,
                'IsGrounded': True,
                'SurfaceFriction': 1.0,
                'GroundNormal': {'x': 0.0, 'y': 1.0, 'z': 0.0},
                'CPDir': {'x': 0.0, 'y': 0.0, 'z': 1.0},
                'CPRelPos': {'x': 0.0, 'y': 0.0, 'z': 0.0},
                'LevelHash': 'BC_TRAIN',
                'ResetReason': 'None'
            }
            env.last_ghost_index = i
            
            obs = env._get_obs()
            
            # Pure Pursuit target steering from lookahead 1 (indices 23 and 25)
            lh1_x = obs[23]
            lh1_z = max(1.0, obs[25])
            angle_to_lookahead = np.arctan2(lh1_x, lh1_z)
            steer_target = float(np.clip(angle_to_lookahead * 2.8, -1.0, 1.0))
            
            observations.append(obs)
            actions.append([steer_target, brake_target, arms_target])
        
    return np.array(observations, dtype=np.float32), np.array(actions, dtype=np.float32)

def pretrain():
    import argparse
    parser = argparse.ArgumentParser(description="Zeepkist AI Behavioral Cloning Pretrainer")
    parser.add_argument("--fresh", action="store_true", help="Start fresh from scratch instead of fine-tuning existing weights")
    parser.add_argument("--epochs", type=int, default=None, help="Number of training epochs")
    args = parser.parse_args()

    print("=" * 60)
    print("Zeepkist AI - Behavioral Cloning (50% Median Ghost Pretrainer)")
    print("=" * 60)

    env = ZeepkistEnv()
    print("Connecting to mod on port 9092 to fetch active level ghost data...")
    env._send_input(0.0, 0.0, 0.0, request_ghost=True)
    
    connected = False
    for attempt in range(1, 11):
        if env._receive_points_from_mod(""):
            connected = True
            break
    if not connected or not env.ghost_frames:
        print("[FALLBACK] Checking saved runs and cached ghosts for offline training data...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        runs_dir = os.path.join(script_dir, "runs")
        found_frames = None
        if os.path.exists(runs_dir):
            for level in os.listdir(runs_dir):
                level_dir = os.path.join(runs_dir, level)
                if os.path.isdir(level_dir):
                    files = [f for f in os.listdir(level_dir) if f.endswith('.json')]
                    if files:
                        files.sort(key=lambda x: os.path.getsize(os.path.join(level_dir, x)), reverse=True)
                        with open(os.path.join(level_dir, files[0]), 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            if 'Frames' in data and len(data['Frames']) > 20:
                                found_frames = data['Frames']
                                print(f"Loaded {len(found_frames)} frames from saved run: {files[0]} ({level})")
                                break
        if found_frames:
            env.ghost_frames = found_frames
        else:
            print("[ERROR] Could not fetch ghost frames from mod or disk! Make sure Zeepkist is running on a track.")
            env.close()
            return

    ghost_frames = env.ghost_frames
    obs, actions = extract_demonstrations(env, ghost_frames)
    print(f"Generated comprehensive recovery dataset with {len(obs)} state-action pairs.")

    # Close initial socket before building vectorized training environment
    env.close()
    time.sleep(0.5)

    dataset = GhostDataset(obs, actions)
    loader = DataLoader(dataset, batch_size=64, shuffle=True)

    venv = DummyVecEnv([lambda: ZeepkistEnv()])
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(script_dir, "zeepkist_ai_model")
    
    # Clean up stale vec_normalize if present
    norm_path = os.path.join(script_dir, "zeepkist_vec_normalize.pkl")
    if os.path.exists(norm_path):
        try: os.remove(norm_path)
        except: pass

    # Back up previous model if one exists
    if os.path.exists(model_path + ".zip"):
        backup_dir = os.path.join(script_dir, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = os.path.join(backup_dir, f"zeepkist_ai_model_backup_{int(time.time())}.zip")
        try:
            import shutil
            shutil.copy2(model_path + ".zip", backup_file)
            print(f"[BACKUP] Existing model archived to {backup_file}")
        except Exception: pass

    # Check for existing model to fine-tune (Continual Learning)
    model = None
    if not args.fresh and os.path.exists(model_path + ".zip"):
        try:
            print("[CONTINUAL LEARNING] Fine-tuning existing PPO model weights on new track demonstrations...")
            model = PPO.load(model_path, env=venv)
            epochs = args.epochs or 400
            lr = 3e-4
        except Exception as e:
            print(f"Could not load existing model ({e}), creating fresh model.")
            model = None

    if model is None:
        print("[NEW MODEL] Initializing fresh PPO policy network...")
        model = PPO("MlpPolicy", venv, verbose=0, learning_rate=1e-4, gamma=0.99, gae_lambda=0.95, ent_coef=0.005)
        epochs = args.epochs or 800
        lr = 1e-3

    policy = model.policy
    optimizer = optim.Adam(policy.parameters(), lr=lr)
    criterion = nn.MSELoss()

    print(f"\nTraining PPO Policy Network ({epochs} epochs, lr={lr})...")
    for epoch in range(1, epochs + 1):
        total_loss = 0.0
        for batch_obs, batch_act in loader:
            optimizer.zero_grad()
            dist = policy.get_distribution(batch_obs)
            pred_act = dist.distribution.mean
            loss = criterion(pred_act, batch_act)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(batch_obs)

        avg_loss = total_loss / len(dataset)
        if epoch % 100 == 0 or epoch == 1 or epoch == epochs:
            print(f"Epoch {epoch:3d}/{epochs} | MSE Loss: {avg_loss:.6f}")

    # Set tight initial exploration standard deviation so policy tracks human lines faithfully
    with torch.no_grad():
        if hasattr(policy, 'log_std') and isinstance(policy.log_std, torch.nn.Parameter):
            policy.log_std.data.fill_(-2.0)

    model.save(model_path)
    venv.close()
    
    print(f"\n[SUCCESS] Pre-trained PPO weights saved to {model_path}.zip!")
    print("You can now run 'start_training.bat' and your car will drive the track on Step 0!")

if __name__ == "__main__":
    pretrain()

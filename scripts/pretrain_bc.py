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
from stable_baselines3 import SAC
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

def extract_demonstrations(ghost_frames):
    env = ZeepkistEnv()
    env.ghost_frames = ghost_frames
    
    observations = []
    actions = []
    
    n_frames = len(ghost_frames)
    print(f"Processing {n_frames} median ghost frames into training observations...")
    
    for i in range(n_frames - 1):
        f = ghost_frames[i]
        f_next = ghost_frames[i + 1]
        
        pos = np.array(f['p'])
        next_pos = np.array(f_next['p'])
        dt = 0.02
        vel_world = (next_pos - pos) / dt
        
        quat = {'x': f['r'][0], 'y': f['r'][1], 'z': f['r'][2], 'w': f['r'][3]}
        
        steer_target = 0.0
        if i < n_frames - 2:
            f_next2 = ghost_frames[i + 2]
            dir1 = next_pos - pos
            dir2 = np.array(f_next2['p']) - next_pos
            cross_y = np.cross(dir1, dir2)[1]
            steer_target = np.clip(cross_y * 2.0, -1.0, 1.0)
            
        brake_target = 1.0 if f.get('b', False) else 0.0
        arms_target = 1.0 if f.get('a', False) else 0.0
        
        env.last_telemetry = {
            'Time': i * dt,
            'Position': {'x': pos[0], 'y': pos[1], 'z': pos[2]},
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
        observations.append(obs)
        actions.append([steer_target, brake_target, arms_target])
        
    return np.array(observations, dtype=np.float32), np.array(actions, dtype=np.float32)

def pretrain():
    print("=" * 60)
    print("Zeepkist AI - Behavioral Cloning (50% Median Ghost Pretrainer)")
    print("=" * 60)

    env = ZeepkistEnv()
    print("Connecting to mod on port 9092 to fetch active level ghost data...")
    connected = False
    for _ in range(5):
        if env._receive_points_from_mod(""):
            connected = True
            break
        time.sleep(1.0)

    if not connected or not env.ghost_frames:
        print("[ERROR] Could not fetch ghost frames from mod! Make sure Zeepkist is running on a track.")
        return

    obs, actions = extract_demonstrations(env.ghost_frames)
    print(f"Generated dataset with {len(obs)} state-action pairs.")

    dataset = GhostDataset(obs, actions)
    loader = DataLoader(dataset, batch_size=64, shuffle=True)

    venv = DummyVecEnv([lambda: ZeepkistEnv()])
    norm_env = VecNormalize(venv, norm_obs=False, norm_reward=False)
    
    model = SAC("MlpPolicy", norm_env, verbose=0)
    actor = model.policy.actor

    optimizer = optim.Adam(actor.parameters(), lr=1e-3)
    criterion = nn.MSELoss()

    print("\nTraining Actor Policy on 50% Median Trajectory...")
    epochs = 300
    for epoch in range(1, epochs + 1):
        total_loss = 0.0
        for batch_obs, batch_act in loader:
            optimizer.zero_grad()
            pred_act = actor(batch_obs)
            loss = criterion(pred_act, batch_act)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(batch_obs)

        avg_loss = total_loss / len(dataset)
        if epoch % 50 == 0 or epoch == 1:
            print(f"Epoch {epoch:3d}/{epochs} | MSE Loss: {avg_loss:.6f}")

    model_path = "zeepkist_ai_model"
    model.save(model_path)
    norm_env.save("zeepkist_vec_normalize.pkl")
    print(f"\n[SUCCESS] Pre-trained weights saved to {model_path}.zip!")
    print("You can now run 'python train.py' and your car will drive the track on Step 0!")

if __name__ == "__main__":
    pretrain()

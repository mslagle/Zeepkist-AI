import gymnasium as gym
from gymnasium import spaces
import numpy as np
import socket
import json
import threading
import time
import os
from parse_ghost import ZeepGhostParser
from fetch_level import get_best_ghost_by_hash, download_file

class ZeepkistEnv(gym.Env):
    def __init__(self, telemetry_port=9090, input_port=9091, host='127.0.0.1'):
        super(ZeepkistEnv, self).__init__()

        self.telemetry_port = telemetry_port
        self.input_port = input_port
        self.host = host

        # Action Space: [Steering, Brake, ArmsUp, Reset]
        # Steering: -1 to 1
        # Brake: 0 to 1
        # ArmsUp: 0 to 1
        # Reset: 0 to 1
        self.action_space = spaces.Box(
            low=np.array([-1.0, 0.0, 0.0, 0.0], dtype=np.float32),
            high=np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32),
            dtype=np.float32
        )

        # Observation Space: 22 dimensions
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(22,),
            dtype=np.float32
        )

        self.telemetry_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.telemetry_socket.bind((self.host, self.telemetry_port))
        self.telemetry_socket.settimeout(0.5) 

        self.input_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.last_telemetry = None
        self.current_level_hash = None
        self.ghost_frames = None
        self.ghost_positions = None
        
        self.max_ghost_index = 0
        self.last_ghost_index = 0
        
        if not os.path.exists("ghosts"):
            os.makedirs("ghosts")

    def _update_ghost_data(self, level_hash):
        if level_hash == self.current_level_hash:
            return
        
        print(f"Detected new level hash: {level_hash}")
        self.current_level_hash = level_hash
        self.ghost_frames = None
        self.ghost_positions = None
        
        ghost_path = f"ghosts/{level_hash}.zeepghost"
        
        if not os.path.exists(ghost_path):
            print(f"Ghost not found locally. Fetching from API...")
            try:
                ghost_url = get_best_ghost_by_hash(level_hash)
                if ghost_url:
                    if download_file(ghost_url, ghost_path):
                        print(f"Ghost downloaded successfully.")
                    else:
                        print(f"Failed to download ghost from {ghost_url}")
                else:
                    print(f"No ghost record found for level hash {level_hash}")
            except Exception as e:
                print(f"Error fetching ghost: {e}")

        if os.path.exists(ghost_path):
            try:
                parser = ZeepGhostParser(ghost_path)
                _, self.ghost_frames = parser.parse()
                if self.ghost_frames:
                    self.ghost_positions = np.array([f['pos'] for f in self.ghost_frames])
                    print(f"Loaded {len(self.ghost_frames)} frames for reward shaping.")
            except Exception as e:
                print(f"Error parsing ghost file: {e}")

    def _clear_telemetry_buffer(self):
        original_timeout = self.telemetry_socket.gettimeout()
        self.telemetry_socket.settimeout(0.0)
        try:
            while True:
                self.telemetry_socket.recvfrom(8192)
        except:
            pass
        self.telemetry_socket.settimeout(original_timeout)

    def _receive_telemetry(self):
        try:
            data, addr = self.telemetry_socket.recvfrom(8192)
            self.last_telemetry = json.loads(data.decode('utf-8'))
            
            if 'LevelHash' in self.last_telemetry:
                self._update_ghost_data(self.last_telemetry['LevelHash'])
                
            return True
        except socket.timeout:
            return False
        except Exception:
            return False

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        self.max_ghost_index = 0
        self.last_ghost_index = 0
        
        print("Sending reset command to game...")
        self._send_input(0.0, False, False, True)
        
        # 1. Wait for game to transition to NOT spawned
        print("Waiting for game to transition (IsSpawned -> False)...")
        start_wait = time.time()
        while time.time() - start_wait < 3.0:
            if self._receive_telemetry():
                if not self.last_telemetry.get('IsSpawned', False):
                    print("Transition confirmed.")
                    break
            time.sleep(0.05)

        self._clear_telemetry_buffer()

        # 2. Wait for game to signal that the player is spawned
        print("Waiting for player to spawn (IsSpawned -> True)...")
        spawned = False
        start_wait = time.time()
        
        while not spawned:
            if self._receive_telemetry():
                if self.last_telemetry.get('IsSpawned', False) and 'Position' in self.last_telemetry:
                    spawned = True
                    print("Player spawned!")
            
            if not spawned:
                time.sleep(0.05)
            
            if time.time() - start_wait > 10.0:
                print("Spawn timeout, retrying reset...")
                self._send_input(0.0, False, False, True)
                time.sleep(0.5)
                self._clear_telemetry_buffer()
                start_wait = time.time()

        time.sleep(0.2)
        self._receive_telemetry()

        observation = self._get_obs()
        return observation, {}

    def _get_nearest_ghost_info(self):
        if self.ghost_positions is None or self.last_telemetry is None or 'Position' not in self.last_telemetry:
            return np.zeros(3), 0, 0.0
        
        pos = np.array([
            self.last_telemetry['Position']['x'],
            self.last_telemetry['Position']['y'],
            self.last_telemetry['Position']['z']
        ])
        
        search_range = 300
        start_idx = max(0, self.last_ghost_index - 50) 
        end_idx = min(len(self.ghost_positions), self.last_ghost_index + search_range)
        
        if self.last_ghost_index == 0:
            distances = np.linalg.norm(self.ghost_positions - pos, axis=1)
            idx = np.argmin(distances)
        else:
            subset = self.ghost_positions[start_idx:end_idx]
            if len(subset) == 0:
                idx = self.last_ghost_index
            else:
                distances = np.linalg.norm(subset - pos, axis=1)
                idx = np.argmin(distances) + start_idx
            
        self.last_ghost_index = idx
        relative_vec = self.ghost_positions[idx] - pos
        progress = idx / len(self.ghost_positions) if len(self.ghost_positions) > 0 else 0.0
        
        return relative_vec, idx, progress

    def _get_obs(self):
        t = self.last_telemetry
        
        if not t or not t.get('IsSpawned', False) or 'Position' not in t:
            return np.zeros(22, dtype=np.float32)

        rel_ghost_vec, _, progress = self._get_nearest_ghost_info()
        ghost_loaded = 1.0 if self.ghost_positions is not None else 0.0
        
        obs = np.array([
            t['Position']['x'], t['Position']['y'], t['Position']['z'],
            t['Rotation']['x'], t['Rotation']['y'], t['Rotation']['z'], t['Rotation']['w'],
            t['Velocity']['x'], t['Velocity']['y'], t['Velocity']['z'],
            t['AngularVelocity']['x'], t['AngularVelocity']['y'], t['AngularVelocity']['z'],
            t['Speed'],
            rel_ghost_vec[0], rel_ghost_vec[1], rel_ghost_vec[2],
            0, 0, 0,
            progress,
            ghost_loaded
        ], dtype=np.float32)
        return obs

    def _calculate_reward(self, obs):
        reward = 0.0
        
        if self.last_ghost_index > self.max_ghost_index:
            progress_gain = self.last_ghost_index - self.max_ghost_index
            reward += progress_gain * 1.0 
            self.max_ghost_index = self.last_ghost_index
            
        reward += 0.01 * obs[13]
        
        dist = np.linalg.norm(obs[14:17])
        reward += max(0, 1.0 - (dist / 10.0))
        
        return reward

    def _send_input(self, steering, brake, arms_up, reset):
        input_data = {
            "Steering": float(steering),
            "Brake": bool(brake),
            "ArmsUp": bool(arms_up),
            "Reset": bool(reset)
        }
        msg = json.dumps(input_data).encode('utf-8')
        try:
            self.input_socket.sendto(msg, (self.host, self.input_port))
        except:
            pass

    def step(self, action):
        # Action: [Steering, Brake, ArmsUp, Reset]
        steering = action[0]
        brake = action[1] > 0.5
        arms_up = action[2] > 0.5
        reset = action[3] > 0.99

        self._send_input(steering, brake, arms_up, reset)

        if not self._receive_telemetry():
            return self._get_obs(), -0.1, False, False, {}

        if not self.last_telemetry.get('IsSpawned', False):
            return self._get_obs(), -20.0, True, False, {}

        obs = self._get_obs()
        reward = self._calculate_reward(obs)
        
        terminated = False
        truncated = False
        
        if obs[1] < -50: 
            reward -= 100.0
            terminated = True
            
        dist = np.linalg.norm(obs[14:17])
        if dist > 100.0 and self.ghost_positions is not None:
            reward -= 50.0
            terminated = True

        return obs, reward, terminated, truncated, {}

    def close(self):
        self.telemetry_socket.close()
        self.input_socket.close()

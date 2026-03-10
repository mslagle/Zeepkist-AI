import gymnasium as gym
from gymnasium import spaces
import numpy as np
import socket
import json
import threading
import time
import os
import sys
from parse_ghost import ZeepGhostParser
from fetch_level import download_file

class ZeepkistEnv(gym.Env):
    def __init__(self, telemetry_port=9090, input_port=9091, host='127.0.0.1'):
        super(ZeepkistEnv, self).__init__()

        self.telemetry_port = telemetry_port
        self.input_port = input_port
        self.points_port = 9092
        self.host = host

        self.action_space = spaces.Box(
            low=np.array([-1.0, 0.0, 0.0], dtype=np.float32),
            high=np.array([1.0, 1.0, 1.0], dtype=np.float32),
            dtype=np.float32
        )

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
        self.points_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.last_telemetry = None
        self.current_level_hash = None
        self.current_ghost_url = None
        self.ghost_frames = None
        self.ghost_positions = None
        
        self.max_ghost_index = 0
        self.last_ghost_index = 0
        self.steps_in_episode = 0
        self.stuck_start_time = None
        self.first_frame_after_reset = True
        
        if not os.path.exists("ghosts"):
            os.makedirs("ghosts")

    def _send_ghost_points(self):
        if self.ghost_positions is None: return
        
        print(f"Sending {len(self.ghost_positions)} points to mod for visualization...")
        # Send a sampled version to mod to keep line renderer performance ok
        # Every 5th point is plenty for a visual line
        sampled = self.ghost_positions[::5]
        
        # Mod expects a JSON with "Points": [[x,y,z], [x,y,z], ...]
        # We send in one big packet if possible, or chunks if too big.
        # UDP limit is ~65kb, 1000 points is ~30kb.
        chunk_size = 500
        for i in range(0, len(sampled), chunk_size):
            chunk = sampled[i : i + chunk_size]
            data = {"Points": chunk.tolist()}
            msg = json.dumps(data).encode('utf-8')
            try:
                self.points_socket.sendto(msg, (self.host, self.points_port))
                time.sleep(0.05) # Delay to allow mod processing
            except: pass

    def _update_ghost_data(self, level_hash, ghost_url):
        if level_hash == self.current_level_hash and ghost_url == self.current_ghost_url and self.ghost_positions is not None:
            return
        
        if not ghost_url:
            return

        print(f"New ghost discovered: {ghost_url} (Level: {level_hash})")
        self.current_level_hash = level_hash
        self.current_ghost_url = ghost_url
        self.ghost_frames = None
        self.ghost_positions = None
        
        ghost_path = f"ghosts/{level_hash}.zeepghost"
        
        if download_file(ghost_url, ghost_path):
            try:
                parser = ZeepGhostParser(ghost_path)
                header, self.ghost_frames = parser.parse()
                if self.ghost_frames:
                    self.ghost_positions = np.array([f['pos'] for f in self.ghost_frames])
                    print(f"Loaded {len(self.ghost_frames)} frames for level {level_hash}")
                    
                    json_path = ghost_path.replace(".zeepghost", ".json")
                    with open(json_path, 'w') as jf:
                        json.dump({'header': header, 'frames': self.ghost_frames}, jf, indent=2)
                    
                    # Notify mod of new points
                    self._send_ghost_points()
                else:
                    raise RuntimeError("Ghost parsed but empty")
            except Exception as e:
                print(f"CRITICAL ERROR parsing ghost: {e}")
                raise e
        else:
            raise RuntimeError(f"Failed to download ghost from {ghost_url}")

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
            
            level_hash = self.last_telemetry.get('LevelHash')
            ghost_url = self.last_telemetry.get('GhostUrl')
            
            if level_hash and ghost_url:
                self._update_ghost_data(level_hash, ghost_url)
                
            return True
        except socket.timeout:
            return False
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise e
            return False

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.max_ghost_index = 0
        self.last_ghost_index = 0
        self.steps_in_episode = 0
        self.stuck_start_time = None
        self.first_frame_after_reset = True
        
        print("--- ENVIRONMENT RESET ---")
        self._send_input(0.0, False, False, reset=True)
        
        start_wait = time.time()
        while time.time() - start_wait < 3.0:
            if self._receive_telemetry():
                if not self.last_telemetry.get('IsSpawned', False):
                    break
            time.sleep(0.05)

        self._clear_telemetry_buffer()

        print("Waiting for player to spawn and ghost data to load...")
        spawned = False
        start_wait = time.time()
        
        while not spawned:
            self._send_input(0.0, False, False, reset=False)
            if self._receive_telemetry():
                if self.last_telemetry.get('IsSpawned', False) and 'Position' in self.last_telemetry and self.ghost_positions is not None:
                    spawned = True
                    print("Ready! Player spawned and ghost loaded.")
            
            if not spawned:
                time.sleep(0.1)
            
            if time.time() - start_wait > 15.0:
                print("Spawn/Ghost timeout, retrying...")
                self._send_input(0.0, False, False, reset=True)
                time.sleep(0.5)
                self._clear_telemetry_buffer()
                start_wait = time.time()

        time.sleep(0.5) 
        self._clear_telemetry_buffer()
        while not self._receive_telemetry():
            time.sleep(0.1)

        return self._get_obs(), {}

    def _get_nearest_ghost_info(self):
        pos = np.array([
            self.last_telemetry['Position']['x'],
            self.last_telemetry['Position']['y'],
            self.last_telemetry['Position']['z']
        ])
        
        if self.first_frame_after_reset:
            subset = self.ghost_positions
            start_idx = 0
            self.first_frame_after_reset = False
        else:
            search_range = 1000
            start_idx = max(0, self.last_ghost_index - 200) 
            end_idx = min(len(self.ghost_positions), self.last_ghost_index + search_range)
            subset = self.ghost_positions[start_idx:end_idx]
        
        if len(subset) == 0:
            idx = self.last_ghost_index
        else:
            diffs = subset[:, [0, 2]] - pos[[0, 2]]
            distances_sq = np.sum(diffs**2, axis=1)
            idx = np.argmin(distances_sq) + start_idx
            
        self.last_ghost_index = idx
        relative_vec = self.ghost_positions[idx] - pos
        progress = idx / len(self.ghost_positions)
        
        return relative_vec, idx, progress

    def _get_obs(self):
        t = self.last_telemetry
        if not t or not t.get('IsSpawned', False) or 'Position' not in t:
            return np.zeros(22, dtype=np.float32)

        rel_ghost_vec, _, progress = self._get_nearest_ghost_info()
        ghost_loaded = 1.0
        
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
        
        if not np.all(np.isfinite(obs)):
            obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)
            
        return obs

    def _calculate_reward(self, obs):
        reward = 0.0
        speed = obs[13]
        if self.last_ghost_index > self.max_ghost_index:
            progress_gain = self.last_ghost_index - self.max_ghost_index
            reward += progress_gain * 5.0
            self.max_ghost_index = self.last_ghost_index
        if speed > 2.0:
            reward += 0.1 * speed
        dist_2d = np.linalg.norm(obs[[14, 16]])
        reward += max(0, 5.0 - (dist_2d / 10.0))
        return reward

    def _send_input(self, steering, brake, arms_up, reset=False):
        input_data = {"Steering": float(steering), "Brake": bool(brake), "ArmsUp": bool(arms_up), "Reset": bool(reset)}
        msg = json.dumps(input_data).encode('utf-8')
        try: self.input_socket.sendto(msg, (self.host, self.input_port))
        except: pass

    def step(self, action):
        self.steps_in_episode += 1
        self._send_input(action[0], action[1] > 0.5, action[2] > 0.5, reset=False)

        if not self._receive_telemetry():
            return self._get_obs(), -0.1, False, False, {}

        if not self.last_telemetry.get('IsSpawned', False):
            return self._get_obs(), -50.0, True, False, {}

        obs = self._get_obs()
        reward = self._calculate_reward(obs)
        speed = obs[13]
        terminated = False
        truncated = False
        
        if obs[1] < -50: terminated = True; reward -= 100.0
        dist_2d = np.linalg.norm(obs[[14, 16]])
        if dist_2d > 300.0: terminated = True; reward -= 50.0

        if speed < 1.0:
            if self.stuck_start_time is None: self.stuck_start_time = time.time()
            elif time.time() - self.stuck_start_time > 5.0: terminated = True; reward -= 30.0
        else: self.stuck_start_time = None
            
        if self.steps_in_episode > 10000: truncated = True
        return obs, reward, terminated, truncated, {}

    def close(self):
        self.telemetry_socket.close()
        self.input_socket.close()
        self.points_socket.close()

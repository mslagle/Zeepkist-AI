import gymnasium as gym
from gymnasium import spaces
import numpy as np
import socket
import json
import threading
import time
import os
import sys

class ZeepkistEnv(gym.Env):
    def __init__(self, telemetry_port=9090, input_port=9091, points_port=9092, host='127.0.0.1'):
        super(ZeepkistEnv, self).__init__()

        self.telemetry_port = telemetry_port
        self.input_port = input_port
        self.points_port = points_port
        self.host = host

        # Action Space: [Steering, Brake, ArmsUp]
        self.action_space = spaces.Box(
            low=np.array([-1.0, 0.0, 0.0], dtype=np.float32),
            high=np.array([1.0, 1.0, 1.0], dtype=np.float32),
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
        
        self.points_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.points_socket.bind((self.host, self.points_port))
        self.points_socket.settimeout(0.1)

        self.last_telemetry = None
        self.current_level_hash = None
        self.ghost_frames = []
        self.ghost_positions = None
        
        self.max_ghost_index = 0
        self.last_ghost_index = 0
        self.steps_in_episode = 0
        self.stuck_start_time = None
        self.first_frame_after_reset = True
        
        if not os.path.exists("ghosts"):
            os.makedirs("ghosts")

    def _receive_points_from_mod(self):
        """Listens for ghost data chunks from the C# mod."""
        print("Listening for ghost data from mod...")
        self.ghost_frames = []
        expected_count = 0
        received_count = 0
        level_hash = "unknown"
        
        timeout_start = time.time()
        while time.time() - timeout_start < 5.0: # 5 second total window to receive ghost
            try:
                data, addr = self.points_socket.recvfrom(65535)
                msg = json.loads(data.decode('utf-8'))
                
                if msg.get("Type") == "Metadata":
                    expected_count = msg.get("FrameCount", 0)
                    level_hash = msg.get("LevelHash", "unknown")
                    print(f"Receiving {expected_count} frames for level {level_hash}")
                    self.ghost_frames = [None] * expected_count
                
                elif msg.get("Type") == "Points":
                    points_chunk = msg.get("Points", [])
                    # Find start index if sent, but our mod just sends sequential chunks
                    # So we track received_count
                    for p in points_chunk:
                        if received_count < len(self.ghost_frames):
                            self.ghost_frames[received_count] = p
                            received_count += 1
                    
                    if msg.get("IsLast") or received_count >= expected_count:
                        break
            except socket.timeout:
                if received_count > 0: continue # Keep waiting if we started receiving
                break
            except Exception as e:
                print(f"Error receiving points: {e}")
                break

        # Clean up and save
        valid_frames = [f for f in self.ghost_frames if f is not None]
        if len(valid_frames) > 0:
            self.current_level_hash = level_hash
            self.ghost_positions = np.array([f['p'] for f in valid_frames])
            print(f"Successfully received {len(valid_frames)} frames from mod.")
            
            # Save JSON as requested
            json_path = f"ghosts/{level_hash}.json"
            with open(json_path, 'w') as jf:
                json.dump({'frames': valid_frames}, jf)
            print(f"Saved ghost JSON to {json_path}")
        else:
            print("Failed to receive valid ghost frames from mod.")

    def _receive_telemetry(self):
        try:
            data, addr = self.telemetry_socket.recvfrom(8192)
            self.last_telemetry = json.loads(data.decode('utf-8'))
            
            new_hash = self.last_telemetry.get('LevelHash')
            if new_hash and new_hash != self.current_level_hash:
                print(f"New level detected: {new_hash}")
                self._receive_points_from_mod()
                
            return True
        except socket.timeout:
            return False
        except Exception:
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

        # Clear buffers
        for sock in [self.telemetry_socket, self.points_socket]:
            original_timeout = sock.gettimeout()
            sock.settimeout(0.0)
            try:
                while True: sock.recvfrom(65535)
            except: pass
            sock.settimeout(original_timeout)

        print("Waiting for player to spawn...")
        spawned = False
        start_wait = time.time()
        
        while not spawned:
            self._send_input(0.0, False, False, reset=False)
            if self._receive_telemetry():
                if self.last_telemetry.get('IsSpawned', False) and 'Position' in self.last_telemetry:
                    # We need ghost data before we can truly be "Ready"
                    if self.ghost_positions is not None:
                        spawned = True
                        print("Ready! Player spawned and ghost data active.")
                    else:
                        print("Waiting for ghost data from mod...")
                        self._receive_points_from_mod()
            
            if not spawned:
                time.sleep(0.1)
            
            if time.time() - start_wait > 20.0:
                print("Reset timeout, retrying...")
                self._send_input(0.0, False, False, reset=True)
                start_wait = time.time()

        return self._get_obs(), {}

    def _get_nearest_ghost_info(self):
        if self.ghost_positions is None:
            return np.zeros(3), 0, 0.0

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
        
        if not np.all(np.isfinite(obs)):
            obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)
            
        return obs

    def _calculate_reward(self, obs, brake_val):
        reward = 0.0
        speed = obs[13]
        if self.last_ghost_index > self.max_ghost_index:
            progress_gain = self.last_ghost_index - self.max_ghost_index
            reward += progress_gain * 5.0
            self.max_ghost_index = self.last_ghost_index
        if speed > 2.0:
            reward += 0.2 * speed
        dist_2d = np.linalg.norm(obs[[14, 16]])
        reward += max(0, 5.0 - (dist_2d / 10.0))
        if brake_val > 0.5:
            reward -= 0.5 * brake_val
        return reward

    def _send_input(self, steering, brake, arms_up, reset=False):
        input_data = {"Steering": float(steering), "Brake": bool(brake), "ArmsUp": bool(arms_up), "Reset": bool(reset)}
        msg = json.dumps(input_data).encode('utf-8')
        try: self.input_socket.sendto(msg, (self.host, self.input_port))
        except: pass

    def step(self, action):
        self.steps_in_episode += 1
        steering, brake_val, arms_up_val = action[0], action[1], action[2]
        self._send_input(steering, brake_val > 0.5, arms_up_val > 0.5, reset=False)

        if not self._receive_telemetry():
            return self._get_obs(), -0.1, False, False, {}

        if not self.last_telemetry.get('IsSpawned', False):
            return self._get_obs(), -50.0, True, False, {}

        obs = self._get_obs()
        reward = self._calculate_reward(obs, brake_val)
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

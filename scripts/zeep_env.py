import gymnasium as gym
from gymnasium import spaces
import numpy as np
import socket
import json
import time
import os
import struct

class ZeepkistEnv(gym.Env):
    def __init__(self, telemetry_port=9090, input_port=9091, points_port=9092, host='127.0.0.1'):
        super(ZeepkistEnv, self).__init__()

        self.telemetry_port = telemetry_port
        self.input_port = input_port
        self.points_port = points_port
        self.host = host

        # Action Space: [Steering (-1 to 1), Brake (0 to 1), ArmsUp (0 to 1)]
        self.action_space = spaces.Box(
            low=np.array([-1.0, 0.0, 0.0], dtype=np.float32),
            high=np.array([1.0, 1.0, 1.0], dtype=np.float32),
            dtype=np.float32
        )

        # Observation Space: 48 dimensions (Physics-Aware)
        # 0-2: Local Velocity
        # 3-5: Local Angular Velocity
        # 6: Speed
        # 7-9: Relative Ghost Position (Local)
        # 10-13: Relative Ghost Rotation (Local Quaternion)
        # 14: Ghost Speed
        # 15-16: Ghost Flags (ArmsUp, Braking)
        # 17-19: Local Ground Normal
        # 20-22: Local Next Checkpoint Direction
        # 23-35: Raycasts (13 distances)
        # 36-38: Lookahead 1 (+50 frames, Rel Pos Local)
        # 39-41: Lookahead 2 (+100 frames, Rel Pos Local)
        # 42: Previous Steering Action
        # 43: Is Slipping (Binary)
        # 44: Surface Friction
        # 45: Progress (0.0 to 1.0)
        # 46: Ghost Loaded (Binary)
        # 47: Groundedness (Derived from rays/friction)
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(48,), dtype=np.float32)

        # Network setup
        self.telemetry_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.telemetry_socket.bind((self.host, self.telemetry_port))
        self.telemetry_socket.settimeout(0.5) 

        self.input_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.last_telemetry = None
        self.current_level_hash = None
        self.ghost_frames = None # List of dicts {p, r, s, a, b}
        
        self.last_ghost_index = 0
        self.steps_in_episode = 0
        self.stuck_start_time = None
        self.last_steering = 0.0
        
        # Cumulative Time Tracking
        self.start_session_time = time.time()
        self.time_file = "zeepkist_total_time.txt"
        self.accumulated_time = 0.0
        if os.path.exists(self.time_file):
            try:
                with open(self.time_file, "r") as f:
                    self.accumulated_time = float(f.read().strip())
                print(f"Loaded cumulative training time: {self.accumulated_time:.1f}s")
            except: pass

        if not os.path.exists("ghosts"):
            os.makedirs("ghosts")

    def _receive_points_from_mod(self, expected_hash):
        print(f"Connecting to mod TCP server for ghost data ({expected_hash})...")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)
                s.connect((self.host, self.points_port))
                
                size_data = s.recv(4)
                if not size_data: return False
                total_size = int.from_bytes(size_data, byteorder='little')
                
                chunks = []
                received = 0
                while received < total_size:
                    chunk = s.recv(min(total_size - received, 65536))
                    if not chunk: break
                    chunks.append(chunk)
                    received += len(chunk)
                
                payload = b"".join(chunks).decode('utf-8')
                msg = json.loads(payload)
                
                if msg.get("LevelHash") != expected_hash: return False
                
                self.ghost_frames = msg.get("Frames", [])
                print(f"Successfully received {len(self.ghost_frames)} rich ghost frames.")
                return True
        except Exception as e:
            print(f"TCP Ghost Error: {e}")
        return False

    def _receive_telemetry(self):
        try:
            data, addr = self.telemetry_socket.recvfrom(8192)
            if not data: return False
            
            ptr = 0
            def read_float():
                nonlocal ptr
                val = struct.unpack('<f', data[ptr:ptr+4])[0]
                ptr += 4
                return float(val)
            def read_bool():
                nonlocal ptr
                val = data[ptr] != 0
                ptr += 1
                return val
            def read_string():
                nonlocal ptr
                length = 0; shift = 0
                while True:
                    byte = data[ptr]; ptr += 1
                    length |= (byte & 0x7F) << shift
                    if (byte & 0x80) == 0: break
                    shift += 7
                val = data[ptr:ptr+length].decode('utf-8')
                ptr += length
                return val

            t = {}
            t['Time'] = read_float()
            t['Position'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['Rotation'] = {'x': read_float(), 'y': read_float(), 'z': read_float(), 'w': read_float()}
            t['Velocity'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['AngularVelocity'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['Speed'] = read_float()
            t['IsSpawned'] = read_bool()
            t['GhostLoaded'] = read_bool()
            t['GhostReady'] = read_bool()
            t['CheckpointReached'] = read_bool()
            
            t['Rays'] = [read_float() for _ in range(13)]
            t['IsSlipping'] = read_bool()
            t['SurfaceFriction'] = read_float()
            
            t['GroundNormal'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['CPDir'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            
            t['LevelHash'] = read_string()
            t['ResetReason'] = read_string()
            
            self.last_telemetry = t
            
            if self.current_level_hash != t['LevelHash']:
                self.current_level_hash = t['LevelHash']
                self.ghost_frames = None
                
            return True
        except: return False

    def _rotate_to_local(self, world_vec, quat):
        # Unity Quat: [x, y, z, w] -> Inverse: [-x, -y, -z, w]
        x, y, z, w = quat['x'], quat['y'], quat['z'], quat['w']
        q_vec = np.array([-x, -y, -z])
        v = np.array(world_vec)
        a = np.cross(q_vec, v) + w * v
        return v + 2 * np.cross(q_vec, a)

    def _get_obs(self):
        t = self.last_telemetry
        if not t or not t.get('IsSpawned', False):
            return np.zeros(48, dtype=np.float32)

        car_pos = np.array([t['Position']['x'], t['Position']['y'], t['Position']['z']])
        car_quat = t['Rotation']
        
        # 1. Local Dynamics
        vel_local = self._rotate_to_local([t['Velocity']['x'], t['Velocity']['y'], t['Velocity']['z']], car_quat)
        ang_vel_local = [t['AngularVelocity']['x'], t['AngularVelocity']['y'], t['AngularVelocity']['z']]
        
        # 2. Ghost Matching
        rel_ghost_pos = np.zeros(3)
        rel_ghost_rot = np.array([0,0,0,1])
        ghost_speed = 0.0
        ghost_flags = [0, 0]
        lookahead1 = np.zeros(3)
        lookahead2 = np.zeros(3)
        progress = 0.0
        
        if self.ghost_frames:
            # Find nearest point (with 500-frame forward window to prevent U-turns)
            search_start = self.last_ghost_index
            search_end = min(len(self.ghost_frames), search_start + 500)
            subset = self.ghost_frames[search_start:search_end]
            
            if len(subset) > 0:
                pos_array = np.array([f['p'] for f in subset])
                dists = np.sum((pos_array - car_pos)**2, axis=1)
                best_local = np.argmin(dists)
                self.last_ghost_index = search_start + best_local
            else:
                # Fallback to full search if lost
                pos_array = np.array([f['p'] for f in self.ghost_frames])
                dists = np.sum((pos_array - car_pos)**2, axis=1)
                self.last_ghost_index = np.argmin(dists)

            gf = self.ghost_frames[self.last_ghost_index]
            rel_ghost_pos = self._rotate_to_local(gf['p'] - car_pos, car_quat)
            # Relative Rotation (Ghost Quat * Inverse Car Quat)
            # For simplicity in ML, we'll just feed the ghost's local rotation
            rel_ghost_rot = gf['r'] # [x,y,z,w]
            ghost_speed = gf['s']
            ghost_flags = [1.0 if gf['a'] else 0.0, 1.0 if gf['b'] else 0.0]
            
            # Lookaheads
            lh1_idx = min(len(self.ghost_frames)-1, self.last_ghost_index + 10) # ~0.5s ahead
            lh2_idx = min(len(self.ghost_frames)-1, self.last_ghost_index + 30) # ~1.5s ahead
            lookahead1 = self._rotate_to_local(np.array(self.ghost_frames[lh1_idx]['p']) - car_pos, car_quat)
            lookahead2 = self._rotate_to_local(np.array(self.ghost_frames[lh2_idx]['p']) - car_pos, car_quat)
            progress = self.last_ghost_index / len(self.ghost_frames)

        # 3. Environment Sensors
        ground_normal_local = self._rotate_to_local([t['GroundNormal']['x'], t['GroundNormal']['y'], t['GroundNormal']['z']], car_quat)
        cp_dir_local = self._rotate_to_local([t['CPDir']['x'], t['CPDir']['y'], t['CPDir']['z']], car_quat)
        
        obs = np.concatenate([
            vel_local, ang_vel_local, [t['Speed']],
            rel_ghost_pos, rel_ghost_rot, [ghost_speed], ghost_flags,
            ground_normal_local, cp_dir_local,
            t['Rays'],
            lookahead1, lookahead2,
            [self.last_steering], [1.0 if t['IsSlipping'] else 0.0], [t['SurfaceFriction']],
            [progress], [1.0 if self.ghost_frames else 0.0],
            [1.0 if t['SurfaceFriction'] > 0.1 else 0.0] # Groundedness
        ]).astype(np.float32)
        
        return np.nan_to_num(obs)

    def _calculate_reward(self, obs, action):
        # 0-2: VelLocal, 7-9: RelGhostPos, 17-19: GroundNormal, 20-22: CPDir
        vel_local = obs[0:3]
        speed = obs[6]
        rel_ghost_pos = obs[7:10]
        cp_dir_local = obs[20:22] # Simplified to 2D heading for primary reward
        
        reward = 0.0
        
        # 1. DIRECTIONAL VELOCITY (Primary)
        # Reward for moving forward relative to the car's heading
        reward += vel_local[2] * 0.1
        
        # 2. PATH ADHERENCE
        dist_to_path = np.linalg.norm(rel_ghost_pos)
        reward += max(0, 1.0 - (dist_to_path / 5.0))
        
        # 3. MOMENTUM CONSERVATION (The "Soapbox" Penalty)
        # Penalize steering more as speed increases
        steering = action[0]
        reward -= abs(steering) * (speed / 50.0) * 0.5
        
        # 4. SWERVING PENALTY
        steering_change = abs(steering - self.last_steering)
        reward -= (steering_change ** 2) * 5.0
        self.last_steering = steering
        
        # 5. LANDING / ORIENTATION
        # If GroundNormal is NOT Up (0,1,0), reward aligning car Up with Ground Normal
        ground_normal = obs[17:20]
        car_up = np.array([0, 1, 0]) # In local space, car up is always 0,1,0
        # We want ground normal (local) to match car up
        alignment = np.dot(ground_normal, car_up)
        reward += alignment * 0.2

        # 6. OBSTACLE AVOIDANCE
        rays = obs[23:36]
        min_ray = np.min(rays)
        if min_ray < 5.0:
            reward -= (5.0 - min_ray) * 0.5

        return reward

    def force_mod_reset(self):
        """Sends an immediate reset signal to the mod without advancing the simulation."""
        print("!!! FORCING MOD RESET FOR BRAIN UPDATE !!!")
        self._send_input(0.0, False, False, reset=True)

    def step(self, action):
        self.steps_in_episode += 1
        steering, brake, arms = action[0], action[1] > 0.5, action[2] > 0.5
        
        # 1:1 Direct Input
        self._send_input(steering, brake, arms)
        
        if not self._receive_telemetry():
            return self._get_obs(), 0.0, False, False, {}

        obs = self._get_obs()
        reward = self._calculate_reward(obs, action)
        
        # Terminal conditions
        terminated = False
        if not self.last_telemetry.get('IsSpawned', False):
            reason = self.last_telemetry.get('ResetReason', 'Unknown')
            print(f"Episode Terminated: IsSpawned=False | Reason: {reason}")
            if reason == "Finished": reward += 1000.0
            else: reward -= 100.0
            terminated = True
            
        if self.steps_in_episode > 15000: 
            print("Episode Terminated: Step Limit reached.")
            terminated = True
        
        return obs, reward, terminated, False, {}

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.steps_in_episode = 0
        self.last_ghost_index = 0
        self.last_steering = 0.0
        
        print("--- RESETTING ---")
        self._send_input(0, False, False, reset=True)
        
        # Wait for respawn and ghost
        while True:
            if self._receive_telemetry():
                if self.last_telemetry['IsSpawned']:
                    level = self.last_telemetry['LevelHash']
                    if self.ghost_frames is None:
                        self._send_input(0, False, False, request_ghost=True)
                        if self._receive_points_from_mod(level):
                            break
                    else: break
            time.sleep(0.1)
            
        # Flush telemetry socket to ensure first step() gets fresh data
        self.telemetry_socket.settimeout(0.0)
        try:
            while True: self.telemetry_socket.recv(8192)
        except: pass
        self.telemetry_socket.settimeout(0.5)

        return self._get_obs(), {}

    def _send_input(self, steering, brake, arms, reset=False, request_ghost=False):
        header = struct.pack('<fBBBB', float(steering), 1 if brake else 0, 1 if arms else 0, 1 if reset else 0, 1 if request_ghost else 0)
        total_time = self.accumulated_time + (time.time() - self.start_session_time)
        input_data = {"p": [[0,0,0]]*4, "t": round(total_time, 1)}
        msg = header + json.dumps(input_data).encode('utf-8')
        try: self.input_socket.sendto(msg, (self.host, self.input_port))
        except: pass

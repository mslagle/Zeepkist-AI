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

        # Observation Space: 44 dimensions
        # 0-13: Basic Telemetry (Pos, Rot, Vel, AngVel, Speed)
        # 14-16: Rel Nearest Ghost Point
        # 17-19: Rel Lookahead 1 (+20 frames)
        # 20-22: Rel Lookahead 2 (+50 frames)
        # 23-25: Rel Lookahead 3 (+100 frames)
        # 26: Progress (0.0 to 1.0)
        # 27: Ghost Loaded Flag (0 or 1)
        # 28-40: Raycasts (13 distances)
        # 41: Previous Steering Action
        # 42: Is Slipping (Binary)
        # 43: Surface Friction
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(44,),
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
        self.last_steering = 0.0 # Track for smoothness
        self.last_target_positions = [[0,0,0]]*4
        self.start_training_time = time.time()
        
        if not os.path.exists("ghosts"):
            os.makedirs("ghosts")

    def _receive_points_from_mod(self, expected_hash):
        """Connects to the C# mod's TCP server to receive ghost data."""
        print(f"Connecting to mod TCP server for level {expected_hash}...")
        
        try:
            # Create a NEW TCP socket for this transfer
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((self.host, self.points_port))
                
                # 1. Read size (4 bytes)
                size_data = s.recv(4)
                if not size_data: return False
                total_size = int.from_bytes(size_data, byteorder='little')
                
                # 2. Read full JSON payload
                chunks = []
                bytes_received = 0
                while bytes_received < total_size:
                    chunk = s.recv(min(total_size - bytes_received, 65536))
                    if not chunk: break
                    chunks.append(chunk)
                    bytes_received += len(chunk)
                
                payload = b"".join(chunks).decode('utf-8')
                msg = json.loads(payload)
                
                received_hash = msg.get("LevelHash", "unknown")
                if received_hash != expected_hash:
                    print(f"Warning: Received TCP data for {received_hash} but expected {expected_hash}")
                    return False
                
                valid_frames = msg.get("Points", [])
                if len(valid_frames) > 0:
                    self.ghost_positions = np.array([f for f in valid_frames])
                    print(f"Successfully received {len(valid_frames)} frames over TCP.")
                    
                    json_path = f"ghosts/{expected_hash}.json"
                    with open(json_path, 'w') as jf:
                        json.dump({'frames': valid_frames}, jf)
                    return True
                    
        except Exception as e:
            print(f"TCP Point Reception Error: {e}")
            
        return False

    def _receive_telemetry(self):
        try:
            # 1. Receive raw bytes
            data, addr = self.telemetry_socket.recvfrom(8192)
            if not data: return False
            
            # 2. Parse Binary Format (Matching mod's BinaryWriter order)
            ptr = 0
            def read_float():
                nonlocal ptr
                val = np.frombuffer(data[ptr:ptr+4], dtype=np.float32)[0]
                ptr += 4
                return float(val)
            
            def read_bool():
                nonlocal ptr
                val = data[ptr] != 0
                ptr += 1
                return val

            def read_string():
                nonlocal ptr
                length = data[ptr]
                ptr += 1
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
            
            t['Rays'] = []
            for _ in range(13):
                t['Rays'].append(read_float())
            
            t['IsSlipping'] = read_bool()
            t['SurfaceFriction'] = read_float()
            
            t['LevelHash'] = read_string()
            t['ResetReason'] = read_string()
            
            self.last_telemetry = t
            
            # Debug: Check for reset reasons
            reason = t.get('ResetReason', 'None')
            if reason != "None" and self.steps_in_episode % 500 == 0:
                print(f"Mod Telemetry Reason: {reason}")

            new_hash = t.get('LevelHash')
            if (new_hash and new_hash != self.current_level_hash) or (self.current_level_hash is None):
                print(f"New level detected in telemetry: {new_hash}")
                self.current_level_hash = new_hash
                self.ghost_positions = None 
                
                # Clear points buffer
                original_timeout = self.points_socket.gettimeout()
                self.points_socket.settimeout(0.0)
                try:
                    while True: self.points_socket.recvfrom(65535)
                except: pass
                self.points_socket.settimeout(original_timeout)
                
            return True
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
        
        # Wait for "not spawned" to confirm reset started
        start_wait = time.time()
        while time.time() - start_wait < 3.0:
            if self._receive_telemetry():
                if not self.last_telemetry.get('IsSpawned', False):
                    print("Reset confirmed: Player unspawned.")
                    break
            time.sleep(0.05)

        # Aggressively clear buffers
        for sock in [self.telemetry_socket, self.points_socket]:
            original_timeout = sock.gettimeout()
            sock.settimeout(0.0)
            try:
                while True: sock.recvfrom(65535)
            except: pass
            sock.settimeout(original_timeout)

        print("Waiting for player to spawn and ghost to load...")
        start_wait = time.time()
        consecutive_spawned = 0
        
        while True:
            t = None
            if self._receive_telemetry():
                t = self.last_telemetry
            
            level_hash = t.get('LevelHash', 'unknown') if t else 'unknown'
            
            # Send input with RequestGhost if we need the data
            need_ghost = (self.ghost_positions is None or self.current_level_hash != level_hash)
            self._send_input(0.0, False, False, reset=False, request_ghost=need_ghost)
            
            if t and t.get('IsSpawned', False):
                consecutive_spawned += 1
                if consecutive_spawned >= 5: # Require 5 stable frames
                    if need_ghost:
                        if t.get('GhostReady', False): # Wait for mod to cache data
                            if self._receive_points_from_mod(level_hash):
                                print("Ready! Player spawned and ghost data active.")
                                break
                            else:
                                print("Ghost reception failed, retrying...")
                                consecutive_spawned = 0
                        else:
                            # Still waiting for mod to parse/cache
                            if self.steps_in_episode % 10 == 0:
                                print("Waiting for mod to signal 'GhostReady'...")
                    else:
                        print("Ready! Ghost already cached.")
                        break
            else:
                consecutive_spawned = 0
            
            time.sleep(0.1)
            if time.time() - start_wait > 30.0:
                print("Reset timeout, retrying full reset...")
                return self.reset()

        # Final buffer clear before starting
        original_timeout = self.telemetry_socket.gettimeout()
        self.telemetry_socket.settimeout(0.0)
        try:
            while True: self.telemetry_socket.recvfrom(65535)
        except: pass
        self.telemetry_socket.settimeout(original_timeout)

        return self._get_obs(), {}

    def _get_nearest_ghost_info(self):
        if self.ghost_positions is None:
            return np.zeros(3), np.zeros((3, 3)), 0, 0.0, [[0,0,0]]*4

        pos = np.array([
            self.last_telemetry['Position']['x'],
            self.last_telemetry['Position']['y'],
            self.last_telemetry['Position']['z']
        ])
        
        # Biased search: only look ahead from the current index.
        # This prevents the AI from ever turning back.
        look_ahead_search = 1000
        start_idx = self.last_ghost_index
        end_idx = min(len(self.ghost_positions), start_idx + look_ahead_search)
        
        subset = self.ghost_positions[start_idx:end_idx]
        
        if len(subset) == 0:
            nearest_idx = self.last_ghost_index
        else:
            diffs = subset - pos
            distances_sq = np.sum(diffs**2, axis=1)
            local_idx = np.argmin(distances_sq)
            
            # nearest_idx is where the car physically is on the path
            nearest_idx = local_idx + start_idx
            
            # Fallback if window is lost (Dist > 10)
            if np.sqrt(distances_sq[local_idx]) > 10.0:
                full_diffs = self.ghost_positions - pos
                full_dist_sq = np.sum(full_diffs**2, axis=1)
                nearest_idx = np.argmin(full_dist_sq)
        
        # Current progress is the nearest point
        self.last_ghost_index = nearest_idx
        
        # TARGET point is always 1 step ahead of nearest to pull the car forward
        target_idx = min(len(self.ghost_positions) - 1, nearest_idx + 1)
        
        target_pos = self.ghost_positions[target_idx]
        relative_vec = target_pos - pos
        
        # Lookahead points relative to the advancing target
        lookaheads = [2, 5, 10]
        lookahead_vecs = []
        target_positions = [target_pos.tolist()]
        for offset in lookaheads:
            l_idx = min(len(self.ghost_positions) - 1, target_idx + offset)
            lookahead_vecs.append(self.ghost_positions[l_idx] - pos)
            target_positions.append(self.ghost_positions[l_idx].tolist())
        
        progress = nearest_idx / len(self.ghost_positions) if len(self.ghost_positions) > 0 else 0.0
        
        if self.steps_in_episode % 100 == 0:
            dist = np.linalg.norm(relative_vec)
            print(f"Path Debug: Nearest={nearest_idx}, Target={target_idx}, DistToTarget={dist:.2f}, Progress={progress:.1%}")

        return relative_vec, np.array(lookahead_vecs), nearest_idx, progress, target_positions

    def _rotate_vector_to_local(self, world_vec, quat):
        """Rotates a world-space vector into the car's local coordinate system."""
        # Unity Quat: [x, y, z, w]
        # Conjugate for inverse rotation: [-x, -y, -z, w]
        x, y, z, w = quat['x'], quat['y'], quat['z'], quat['w']
        q_vec = np.array([-x, -y, -z])
        v = np.array(world_vec)
        
        # v' = v + 2 * cross(q_vec, cross(q_vec, v) + w * v)
        a = np.cross(q_vec, v) + w * v
        return v + 2 * np.cross(q_vec, a)

    def _get_obs(self):
        t = self.last_telemetry
        if not t or not t.get('IsSpawned', False) or 'Position' not in t:
            self.last_target_positions = [[0,0,0]]*4
            return np.zeros(44, dtype=np.float32)

        car_quat = t['Rotation']
        
        # 1. Transform ghost vectors to Local Space
        rel_near_world, lookaheads_world, idx, progress, target_positions = self._get_nearest_ghost_info()
        self.last_target_positions = target_positions
        
        rel_near_local = self._rotate_vector_to_local(rel_near_world, car_quat)
        lookaheads_local = np.array([self._rotate_vector_to_local(v, car_quat) for v in lookaheads_world])
        
        # 2. Transform Velocity to Local Space
        vel_world = [t['Velocity']['x'], t['Velocity']['y'], t['Velocity']['z']]
        vel_local = self._rotate_vector_to_local(vel_world, car_quat)
        
        # 3. Path Direction Awareness
        # Get vector between current ghost point and next one to know path heading
        next_idx = min(len(self.ghost_positions) - 1, idx + 1)
        path_dir_world = self.ghost_positions[next_idx] - self.ghost_positions[idx]
        if np.linalg.norm(path_dir_world) > 0.001:
            path_dir_world /= np.linalg.norm(path_dir_world)
        path_dir_local = self._rotate_vector_to_local(path_dir_world, car_quat)

        ghost_loaded = 1.0 if self.ghost_positions is not None else 0.0
        rays = t.get('Rays', [40.0, 40.0, 40.0, 10.0, 10.0])
        
        # 44-dim observation (Local frame)
        obs = np.concatenate([
            vel_local,
            [t['AngularVelocity']['x'], t['AngularVelocity']['y'], t['AngularVelocity']['z']],
            [t['Speed']],
            rel_near_local,
            lookaheads_local.flatten(),
            path_dir_local,
            [progress],
            [ghost_loaded],
            rays,
            [car_quat['x'], car_quat['y'], car_quat['z'], car_quat['w']],
            [self.last_steering],
            [1.0 if t.get('IsSlipping', False) else 0.0],
            [t.get('SurfaceFriction', 1.0)]
        ]).astype(np.float32)

        
        if not np.all(np.isfinite(obs)):
            obs = np.nan_to_num(obs, nan=0.0, posinf=0.0, neginf=0.0)
            
        return obs

    def _calculate_reward(self, obs, steering, brake_val):
        # Index Map (42 Dims):
        # 0-2: Local Vel, 3-5: Ang Vel, 6: Speed
        # 7-9: Local Rel Near Ghost
        # 10-18: Lookaheads, 19-21: Path Dir, 22: Progress
        # 23: Ghost Loaded, 24-36: Rays, 37-40: Quat, 41: Prev Steering
        
        # We need to update this logic to use the new dimensions correctly. 
        # Wait, the previous dimension count was 44 in my head but 42 here.
        # Let me re-verify. 
        # concatenate: vel(3), ang(3), speed(1), rel(3), look(9), path(3), 
        # prog(1), loaded(1), rays(13), quat(4), prev_steer(1) = 42. Correct.
        
        # Let's add Slipping(1) and Friction(1) to make it 44 as planned.
        # But first let's fix the 42-dim logic.
        
        reward = 0.0
        local_vel = obs[0:3]
        speed = obs[6]
        rel_near_local = obs[7:10]
        path_dir_local = obs[19:22]
        rays = obs[24:37]
        
        # 1. Track-Aligned Velocity
        alignment = np.dot(local_vel, path_dir_local)
        if alignment > 0:
            reward += alignment * 0.5
        else:
            reward -= 0.1 
            
        # 2. Path Proximity Bonus
        dist_3d = np.linalg.norm(rel_near_local)
        proximity_bonus = max(0, 2.0 * (1.0 - (dist_3d / 10.0)))
        reward += proximity_bonus
        
        # 3. New Milestone Reward
        if self.last_ghost_index > self.max_ghost_index:
            progress_gain = self.last_ghost_index - self.max_ghost_index
            reward += progress_gain * 10.0
            self.max_ghost_index = self.last_ghost_index

        # 4. Smoothness & Control
        # Speed-scaled magnitude penalty
        speed_factor = 1.0 + (speed / 50.0)
        steering_penalty = abs(steering) * 0.2 * speed_factor
        
        # Quadratic change penalty
        steering_change = abs(steering - self.last_steering)
        smoothness_penalty = (steering_change ** 2) * 5.0
        
        reward -= (steering_penalty + smoothness_penalty)
        self.last_steering = steering

        # 5. Collision Avoidance (13 Rays)
        proximity_threshold = min(30.0, 3.0 + (speed * 0.3))
        proximity_penalty = 0.0
        weights = [0.2, 0.3, 0.5, 0.7, 0.9, 1.0, 1.0, 1.0, 0.9, 0.7, 0.5, 0.3, 0.2]
        for i, r_dist in enumerate(rays):
            if r_dist < proximity_threshold:
                depth = (proximity_threshold - r_dist) / proximity_threshold
                proximity_penalty += (depth ** 2) * 10.0 * weights[i]
        reward -= proximity_penalty

        # 6. Braking Penalty
        if brake_val > 0.5 and speed < 15.0:
            reward -= 5.0 * brake_val
            
        return reward

    def _send_input(self, steering, brake, arms_up, reset=False, request_ghost=False):
        import struct
        # Binary Input Format:
        # [0-3]: Steering (float)
        # [4]: Brake (bool)
        # [5]: ArmsUp (bool)
        # [6]: Reset (bool)
        # [7]: RequestGhost (bool)
        
        # 1. Pack basic controls (8 bytes)
        header = struct.pack('<fBBBB', 
            float(steering),
            1 if brake else 0,
            1 if arms_up else 0,
            1 if reset else 0,
            1 if request_ghost else 0
        )
        
        # 2. Append TargetPositions and Time as JSON
        input_data = {
            "p": [[round(c, 2) for c in pos] for pos in self.last_target_positions],
            "t": round(time.time() - self.start_training_time, 1)
        }
        targets_json = json.dumps(input_data)
        msg = header + targets_json.encode('utf-8')
        
        try: self.input_socket.sendto(msg, (self.host, self.input_port))
        except: pass

    def step(self, action):
        self.steps_in_episode += 1
        steering, brake_val, arms_up_val = action[0], action[1], action[2]
        self._send_input(steering, brake_val > 0.5, arms_up_val > 0.5, reset=False)

        if not self._receive_telemetry():
            return self._get_obs(), -0.1, False, False, {}

        terminated = False
        truncated = False
        obs = self._get_obs()
        reward = self._calculate_reward(obs, steering, brake_val)
        
        # Checkpoint Reward
        if self.last_telemetry.get('CheckpointReached', False):
            print(f"  [REWARD] Checkpoint Reached! +100.0")
            reward += 100.0

        # New Indices: 6 is Speed, 15 is Relative Y (Drop)
        speed = obs[6]
        
        reason = self.last_telemetry.get('ResetReason', 'None')

        if not self.last_telemetry.get('IsSpawned', False):
            if reason == "Finished":
                print(f"Episode End: FINISHED! | Final Bonus: +1000.0")
                return obs, 1000.0, True, False, {}
            else:
                print(f"Episode End: Not Spawned (Reason: {reason}) | Final Penalty: -50.0")
                return obs, -50.0, True, False, {}

        if obs[8] > 20.0: # Index 8 is local Y of the relative ghost vector (ghost_y - pos_y)
            print(f"Episode End: Fell off map (Drop: {obs[8]:.1f}) | Final Penalty: -100.0")
            terminated = True; reward -= 100.0
        
        # dist_2d is now calculated from local X and Z (indices 7 and 9)
        dist_2d = np.linalg.norm([obs[7], obs[9]])
        if dist_2d > 25.0: 
            print(f"Episode End: Too far from ghost (Dist: {dist_2d:.1f}) | Final Penalty: -50.0")
            terminated = True; reward -= 50.0

        if speed < 1.0:
            if self.stuck_start_time is None: self.stuck_start_time = time.time()
            elif time.time() - self.stuck_start_time > 5.0: 
                print("Episode End: Stuck | Final Penalty: -30.0")
                terminated = True; reward -= 30.0
        else: self.stuck_start_time = None
            
        if self.steps_in_episode > 10000: 
            print("Episode End: Step limit reached")
            truncated = True
            
        return obs, reward, terminated, truncated, {}

    def close(self):
        self.telemetry_socket.close()
        self.input_socket.close()
        self.points_socket.close()

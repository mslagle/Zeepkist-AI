import gymnasium as gym
from gymnasium import spaces
import numpy as np
import socket
import json
import time
import os
import struct

class ZeepkistEnv(gym.Env):
    def __init__(self, telemetry_port=9090, input_port=9091, points_port=9092, host='127.0.0.1', use_curriculum=False):
        super(ZeepkistEnv, self).__init__()

        self.telemetry_port = telemetry_port
        self.input_port = input_port
        self.points_port = points_port
        self.host = host
        self.use_curriculum = use_curriculum

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
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(35,), dtype=np.float32)

        # Network setup
        self.telemetry_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.telemetry_socket.bind((self.host, self.telemetry_port))
        self.telemetry_socket.settimeout(0.5) 

        self.input_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        self.last_telemetry = None
        self.current_level_hash = None
        self.ghost_frames = None # List of dicts {p, r, s, a, b}
        
        self.last_ghost_index = 0
        self.max_ghost_index = 0
        self.global_max_ghost_index = 0
        self.steps_in_episode = 0
        self.stuck_start_time = None
        self.last_steering = 0.0
        self.episode_reward = 0.0
        self.last_log_time = time.time()
        
        # Cumulative Time Tracking
        self.initial_unity_time = None
        self.current_unity_time = 0.0
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
            if self.initial_unity_time is None:
                self.initial_unity_time = t['Time']
            self.current_unity_time = t['Time']
            
            t['Position'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['Rotation'] = {'x': read_float(), 'y': read_float(), 'z': read_float(), 'w': read_float()}
            t['Velocity'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['AngularVelocity'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['Speed'] = read_float()
            t['IsSpawned'] = read_bool()
            t['GhostLoaded'] = read_bool()
            t['GhostReady'] = read_bool()
            t['CheckpointReached'] = read_bool()

            t['IsSlipping'] = read_bool()
            t['IsGrounded'] = read_bool()
            t['SurfaceFriction'] = read_float()
            
            t['GroundNormal'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['CPDir'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            t['CPRelPos'] = {'x': read_float(), 'y': read_float(), 'z': read_float()}
            
            t['LevelHash'] = read_string()
            t['ResetReason'] = read_string()
            
            self.last_telemetry = t
            
            if self.current_level_hash != t['LevelHash']:
                self.current_level_hash = t['LevelHash']
                self.ghost_frames = None
                self.global_max_ghost_index = 0
                
            return True
        except Exception: return False

    def _rotate_to_local(self, world_vec, quat):
        # Unity Quat: [x, y, z, w] -> Inverse: [-x, -y, -z, w]
        x, y, z, w = quat['x'], quat['y'], quat['z'], quat['w']
        q_vec = np.array([-x, -y, -z])
        v = np.array(world_vec)
        a = np.cross(q_vec, v) + w * v
        return v + 2 * np.cross(q_vec, a)

    def _relative_quaternion(self, q_car, q_ghost):
        # q_car (t['Rotation']): {'x':..., 'y':..., 'z':..., 'w':...}
        # q_ghost (gf['r']): list [x,y,z,w]
        # Calculate q_inv = [-q_car.x, -q_car.y, -q_car.z, q_car.w]
        ax, ay, az, aw = -q_car['x'], -q_car['y'], -q_car['z'], q_car['w']
        bx, by, bz, bw = q_ghost[0], q_ghost[1], q_ghost[2], q_ghost[3]
        
        # Hamilton product: q_inv * q_ghost
        x = aw * bx + ax * bw + ay * bz - az * by
        y = aw * by - ax * bz + ay * bw + az * bx
        z = aw * bz + ax * by - ay * bx + az * bw
        w = aw * bw - ax * bx - ay * by - az * bz
        return np.array([x, y, z, w], dtype=np.float32)

    def _get_obs(self):
        t = self.last_telemetry
        if not t or not t.get('IsSpawned', False):
            self.fallen_off = False
            return np.zeros(35, dtype=np.float32)

        car_pos = np.array([t['Position']['x'], t['Position']['y'], t['Position']['z']])
        car_quat = t['Rotation']
        
        # 1. Local Dynamics
        vel_local = self._rotate_to_local([t['Velocity']['x'], t['Velocity']['y'], t['Velocity']['z']], car_quat)
        ang_vel_local = self._rotate_to_local([t['AngularVelocity']['x'], t['AngularVelocity']['y'], t['AngularVelocity']['z']], car_quat)
        
        # 2. Ghost Matching
        rel_ghost_pos = np.zeros(3)
        rel_ghost_rot = np.array([0,0,0,1])
        ghost_speed = 0.0
        ghost_flags = [0, 0]
        lookahead1 = np.zeros(3)
        lookahead2 = np.zeros(3)
        progress = 0.0
        
        self.fallen_off = False
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
            self.fallen_off = (gf['p'][1] - car_pos[1]) > 15.0
            rel_ghost_pos = self._rotate_to_local(gf['p'] - car_pos, car_quat)
            # Relative Rotation (Ghost Quat * Inverse Car Quat)
            rel_ghost_rot = self._relative_quaternion(car_quat, gf['r'])
            ghost_speed = gf['s']
            ghost_flags = [1.0 if gf['a'] else 0.0, 1.0 if gf['b'] else 0.0]
            
            # Lookaheads
            lh1_idx = min(len(self.ghost_frames)-1, self.last_ghost_index + 30) # ~1.5s ahead
            lh2_idx = min(len(self.ghost_frames)-1, self.last_ghost_index + 60) # ~3.0s ahead
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
            lookahead1, lookahead2,
            [self.last_steering], [1.0 if t['IsSlipping'] else 0.0], [t['SurfaceFriction']],
            [progress], [1.0 if self.ghost_frames else 0.0],
            [1.0 if t['IsGrounded'] else 0.0] # Groundedness
        ]).astype(np.float32)
        
        return np.nan_to_num(obs)

    def _calculate_reward(self, obs, action):
        # 0-2: VelLocal, 7-9: RelGhostPos, 17-19: GroundNormal, 20-22: CPDir
        # Since we removed Rays (75 values), the new index of IsGrounded is 34.
        vel_local = obs[0:3]
        speed = obs[6]
        rel_ghost_pos = obs[7:10]
        is_grounded = obs[34] > 0.5
        ghost_is_braking = obs[16] > 0.5
        
        reward = 0.0
        
        # 0. CHECKPOINT BONUS (Mandatory for completion)
        if self.last_telemetry.get('CheckpointReached', False):
            reward += 500.0
            print(f"[REWARD] Checkpoint reached! +500")

        # 1. PROGRESS REWARD (Primary)
        if self.last_ghost_index > self.max_ghost_index:
            reward += (self.last_ghost_index - self.max_ghost_index) * 5.0
            self.max_ghost_index = self.last_ghost_index
        
        # 2. SPEED ON PATH (Primary continuous reward: speed in direction of path * path adherence)
        dist_to_path = np.linalg.norm(rel_ghost_pos)
        speed_on_path = vel_local[2] * np.exp(-dist_to_path * 0.3)
        reward += speed_on_path * 0.5
        
        # 4. MOMENTUM CONSERVATION (Smooth steering)
        steering = action[0]
        reward -= abs(steering) * (speed / 100.0) * 0.05
        
        # 5. SWERVING PENALTY
        steering_change = abs(steering - self.last_steering)
        reward -= (steering_change ** 2) * 2.0
        self.last_steering = steering
        
        # 6. LANDING / ORIENTATION ALIGNMENT
        ground_normal = obs[17:20]
        car_up = np.array([0, 1, 0])
        alignment = np.dot(ground_normal, car_up)
        reward += alignment * 0.1

        # 7. BRAKING PENALTY
        brake_input = action[1]
        if brake_input > 0.01:
            if is_grounded:
                if not ghost_is_braking:
                    reward -= brake_input * 5.0
                else:
                    reward -= brake_input * 0.1
            else:
                ang_vel_mag = np.linalg.norm(obs[3:6])
                spin_factor = max(0.0, 1.0 - ang_vel_mag / 1.0)
                reward -= brake_input * spin_factor * 1.0

        # 7.5 AIR SPIN PENALTY
        if not is_grounded:
            ang_vel_mag = np.linalg.norm(obs[3:6])
            reward -= ang_vel_mag * 0.05

        return reward

    def force_mod_reset(self):
        """Sends an immediate reset signal to the mod without advancing the simulation."""
        print("!!! FORCING MOD RESET FOR BRAIN UPDATE !!!")
        self._send_input(0.0, 0.0, 0.0, reset=True)

    def step(self, action):
        self.steps_in_episode += 1
        steering, brake, arms = action[0], action[1], action[2]
        
        # 1:1 Direct Input
        self._send_input(steering, brake, arms)
        
        if not self._receive_telemetry():
            return self._get_obs(), 0.0, False, False, {}

        obs = self._get_obs()
        reward = self._calculate_reward(obs, action)
        self.episode_reward += reward
        
        if self.last_ghost_index > self.global_max_ghost_index:
            self.global_max_ghost_index = self.last_ghost_index
        
        # Stuck Detection
        speed = obs[6]
        terminated = False
        if speed < 1.0:
            if self.stuck_start_time is None:
                self.stuck_start_time = time.time()
            elif time.time() - self.stuck_start_time > 5.0:
                print(f"[RESET] Reason: Stuck (Speed < 1.0 for 5s) | Ep Reward: {self.episode_reward:.2f}")
                terminated = True
        else:
            self.stuck_start_time = None

        # Periodic Status Logging (Every 30 seconds)
        now = time.time()
        if now - self.last_log_time > 30.0:
            session_delta = 0.0
            if self.initial_unity_time is not None:
                session_delta = self.current_unity_time - self.initial_unity_time
            total_time = self.accumulated_time + session_delta
            print(f"[STATUS] Time: {int(total_time)}s | Ep Steps: {self.steps_in_episode} | Ep Reward: {self.episode_reward:.2f}")
            self.last_log_time = now

        # Terminal conditions
        if not terminated:
            if getattr(self, 'fallen_off', False):
                print(f"[RESET] Reason: Fell off track (>15m below ghost) | Ep Reward: {self.episode_reward:.2f}")
                reward -= 100.0
                terminated = True
            elif not self.last_telemetry.get('IsSpawned', False):
                reason = self.last_telemetry.get('ResetReason', 'Unknown')
                print(f"[RESET] Reason: {reason} | Ep Reward: {self.episode_reward:.2f}")
                if reason == "Finished": reward += 1000.0
                else: reward -= 100.0
                terminated = True
                
            if self.steps_in_episode > 15000: 
                print(f"[RESET] Reason: Step Limit Reached | Ep Reward: {self.episode_reward:.2f}")
                terminated = True
        
        return obs, reward, terminated, False, {}

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.steps_in_episode = 0
        
        # Sample spawn index using Curriculum Learning
        spawn_index = -1
        if self.use_curriculum and self.ghost_frames and getattr(self, 'global_max_ghost_index', 0) > 50:
            if np.random.rand() < 0.5:
                max_start = min(len(self.ghost_frames) - 20, int(self.global_max_ghost_index - 30))
                if max_start > 0:
                    spawn_index = int(np.random.randint(1, max_start))
                    
        self.last_ghost_index = max(0, spawn_index)
        self.max_ghost_index = max(0, spawn_index)
        self.last_steering = 0.0
        self.episode_reward = 0.0
        self.stuck_start_time = None
        
        print(f"\n--- NEW RACE STARTING (Spawn Index: {max(0, spawn_index)} / Furthest: {self.global_max_ghost_index}) ---")
        self._send_input(0.0, 0.0, 0.0, reset=True, spawn_index=spawn_index)
        
        # 1. Wait for IsSpawned to become False (ensure reset processed)
        self.telemetry_socket.settimeout(0.02)
        start_wait_false = time.time()
        while time.time() - start_wait_false < 3.0:
            if self._receive_telemetry():
                if not self.last_telemetry.get('IsSpawned', False):
                    break
            else:
                # Timeout occurred, meaning no packets are coming (level is loading)
                break
        self.telemetry_socket.settimeout(0.5)

        # 2. Wait for IsSpawned to become True (ensure car spawned)
        start_wait_true = time.time()
        while time.time() - start_wait_true < 30.0:
            try:
                if self._receive_telemetry():
                    if self.last_telemetry.get('IsSpawned', False):
                        level = self.last_telemetry['LevelHash']
                        if self.ghost_frames is None:
                            self._send_input(0.0, 0.0, 0.0, request_ghost=True)
                            if self._receive_points_from_mod(level):
                                break
                        else: break
                time.sleep(0.05)
            except KeyboardInterrupt:
                print("\nReset interrupted by user.")
                raise
        else:
            print("Reset timed out after 30 seconds. Car may not be spawned.")
            
        # Flush telemetry socket to ensure first step() gets fresh data
        self.telemetry_socket.settimeout(0.0)
        try:
            while True: self.telemetry_socket.recv(8192)
        except Exception: pass
        self.telemetry_socket.settimeout(0.5)

        return self._get_obs(), {}

    def save_time(self):
        """Persists total cumulative training time to disk."""
        session_delta = 0.0
        if self.initial_unity_time is not None:
            session_delta = self.current_unity_time - self.initial_unity_time
        total = self.accumulated_time + session_delta
        try:
            with open(self.time_file, "w") as f:
                f.write(str(total))
        except Exception as e:
            print(f"Error saving time file: {e}")

    def close(self):
        self.save_time()
        self.telemetry_socket.close()
        self.input_socket.close()

    def _send_input(self, steering, brake, arms, reset=False, request_ghost=False, spawn_index=-1):
        header = struct.pack('<fffBBi', float(steering), float(brake), float(arms), 1 if reset else 0, 1 if request_ghost else 0, int(spawn_index))
        
        session_delta = 0.0
        if self.initial_unity_time is not None:
            session_delta = self.current_unity_time - self.initial_unity_time
            
        total_time = self.accumulated_time + session_delta
        input_data = {"p": [[0,0,0]]*4, "t": round(total_time, 1)}
        msg = header + json.dumps(input_data).encode('utf-8')
        try: self.input_socket.sendto(msg, (self.host, self.input_port))
        except Exception: pass

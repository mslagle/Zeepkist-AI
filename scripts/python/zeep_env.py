import gymnasium as gym
from gymnasium import spaces
import numpy as np
import socket
import json
import time
import os
import re
import struct

def append_training_log(msg):
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(script_dir, "zeepkist_training.log"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
            f.flush()
    except Exception:
        pass

def json_numpy_default(obj):
    if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float32, np.float64)):
        return float(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

class ZeepkistEnv(gym.Env):
    def __init__(self, telemetry_port=9090, input_port=9091, points_port=9092, host='127.0.0.1', use_curriculum=False, instance_id=None):
        super(ZeepkistEnv, self).__init__()

        if instance_id is not None:
            port_offset = instance_id * 10
            self.telemetry_port = 9090 + port_offset
            self.input_port = 9091 + port_offset
            self.points_port = 9092 + port_offset
        else:
            self.telemetry_port = telemetry_port
            self.input_port = input_port
            self.points_port = points_port

        self.instance_id = instance_id if instance_id is not None else 0
        self.host = host
        self.use_curriculum = use_curriculum

        # Action Space: [Steering (-1 to 1), Brake (0 to 1), ArmsUp (0 to 1)]
        self.action_space = spaces.Box(
            low=np.array([-1.0, 0.0, 0.0], dtype=np.float32),
            high=np.array([1.0, 1.0, 1.0], dtype=np.float32),
            dtype=np.float32
        )

        # Observation space: 35 Continuous values
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(35,), dtype=np.float32)

        # Network setup
        self.telemetry_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.telemetry_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
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
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.time_file = os.path.join(script_dir, "zeepkist_total_time.txt")
        self.accumulated_time = 0.0
        if os.path.exists(self.time_file):
            try:
                with open(self.time_file, "r") as f:
                    self.accumulated_time = float(f.read().strip())
                print(f"Loaded cumulative training time: {self.accumulated_time:.1f}s")
            except: pass

        # Run Recording System (Stores all runs in same JSON schema as ghosts for replay)
        self.runs_dir = os.path.join(script_dir, "runs")
        os.makedirs(self.runs_dir, exist_ok=True)
        self.current_episode_frames = []

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
                
                if expected_hash and msg.get("LevelHash") != expected_hash:
                    print(f"TCP Ghost hash mismatch: received {msg.get('LevelHash')}, expected {expected_hash}")
                    return False
                
                self.ghost_frames = msg.get("Frames", [])
                print(f"Successfully received {len(self.ghost_frames)} rich ghost frames (Level: {msg.get('LevelHash')}).")
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
        self.veered_off = False
        if self.ghost_frames:
            # Generous forward search window (100 frames ~ 2.0s) so high speed does not clamp
            search_start = max(0, self.last_ghost_index - 10)
            search_end = min(len(self.ghost_frames), self.last_ghost_index + 100)
            subset = self.ghost_frames[search_start:search_end]
            
            if len(subset) > 0:
                pos_array = np.array([f['p'] for f in subset])
                dists = np.sum((pos_array - car_pos)**2, axis=1)
                best_local = np.argmin(dists)
                self.last_ghost_index = search_start + best_local
            else:
                # Fallback search
                search_start_back = max(0, self.last_ghost_index - 20)
                search_end_fwd = min(len(self.ghost_frames), self.last_ghost_index + 120)
                pos_array = np.array([f['p'] for f in self.ghost_frames[search_start_back:search_end_fwd]])
                dists = np.sum((pos_array - car_pos)**2, axis=1)
                self.last_ghost_index = search_start_back + np.argmin(dists)

            gf = self.ghost_frames[self.last_ghost_index]
            dist_to_line = np.linalg.norm(np.array(gf['p']) - car_pos)
            
            # Failure Conditions: Only check veering after starting grid warmup (step > 30)
            if self.steps_in_episode > 30 and self.last_ghost_index > 5:
                self.veered_off = dist_to_line > 15.0
                self.fallen_off = (gf['p'][1] - car_pos[1]) > 15.0 or self.veered_off
            else:
                self.veered_off = False
                self.fallen_off = False
            
            rel_ghost_pos = self._rotate_to_local(gf['p'] - car_pos, car_quat)
            # Relative Rotation (Ghost Quat * Inverse Car Quat)
            rel_ghost_rot = self._relative_quaternion(car_quat, gf['r'])
            ghost_speed = gf['s']
            ghost_flags = [1.0 if gf['a'] else 0.0, 1.0 if gf['b'] else 0.0]
            
            # Lookaheads (Responsive short ~0.25s and medium ~0.6s)
            lh1_idx = min(len(self.ghost_frames)-1, self.last_ghost_index + 12)
            lh2_idx = min(len(self.ghost_frames)-1, self.last_ghost_index + 30)
            lookahead1 = self._rotate_to_local(np.array(self.ghost_frames[lh1_idx]['p']) - car_pos, car_quat)
            lookahead2 = self._rotate_to_local(np.array(self.ghost_frames[lh2_idx]['p']) - car_pos, car_quat)

            # Road tangent direction along the track spline (curve guidance)
            tangent_world = np.array(self.ghost_frames[lh1_idx]['p']) - np.array(gf['p'])
            tangent_norm = np.linalg.norm(tangent_world)
            if tangent_norm > 1e-3:
                track_dir_world = tangent_world / tangent_norm
            else:
                track_dir_world = np.array([0.0, 0.0, 1.0])
            track_dir_local = self._rotate_to_local(track_dir_world, car_quat)
            progress = self.last_ghost_index / len(self.ghost_frames)
        else:
            track_dir_local = self._rotate_to_local([t['CPDir']['x'], t['CPDir']['y'], t['CPDir']['z']], car_quat)

        # 3. Environment Sensors
        ground_normal_local = self._rotate_to_local([t['GroundNormal']['x'], t['GroundNormal']['y'], t['GroundNormal']['z']], car_quat)
        
        obs = np.concatenate([
            vel_local, ang_vel_local, [t['Speed']],
            rel_ghost_pos, rel_ghost_rot, [ghost_speed], ghost_flags,
            ground_normal_local, track_dir_local,
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
        
        # 0. TIME COST (Small step penalty so faster completion times earn higher cumulative return)
        reward = -0.05

        # 1. CHECKPOINTS (+1,000)
        if self.last_telemetry.get('CheckpointReached', False):
            reward += 1000.0
            print(f"[REWARD] Checkpoint reached! +1000")

        # 2. DISTANCE / TRACK PROGRESS (+25 per new waypoint along median ghost spline)
        if self.last_ghost_index > self.max_ghost_index:
            new_waypoints = self.last_ghost_index - self.max_ghost_index
            reward += new_waypoints * 25.0
            self.max_ghost_index = self.last_ghost_index
        
        # 3. SPEED & LINE FOLLOWING (Rewards matching and exceeding ghost speed on the line)
        dist_to_path = np.linalg.norm(rel_ghost_pos)
        track_dir_local = obs[20:23]
        road_heading_alignment = max(0.0, float(track_dir_local[2]))
        target_ghost_speed = max(10.0, float(obs[14]))

        # Line accuracy factor (1.0 right on centerline, decays as car drifts)
        on_line_factor = road_heading_alignment * np.exp(-dist_to_path * 0.4)
        
        # Speed ratio: current speed vs. recorded median ghost speed
        speed_ratio = speed / target_ghost_speed

        # Scaled reward: matching speed gives +2.0, exceeding ghost speed gives accelerated bonus!
        if speed_ratio >= 1.0:
            speed_reward = 2.0 + (speed_ratio - 1.0) * 3.0  # High bonus for exceeding human speed
        else:
            speed_reward = speed_ratio * 2.0  # Proportional ramp-up as speed approaches ghost

        reward += speed_reward * on_line_factor

        # Off-line penalty (if drifting > 3.0m away from the line)
        if dist_to_path > 3.0:
            reward -= (dist_to_path - 3.0) * 0.5
        
        # 4. MOMENTUM CONSERVATION & SMOOTHNESS
        steering = action[0]
        reward -= abs(steering) * (speed / 100.0) * 0.03
        
        steering_change = abs(steering - self.last_steering)
        reward -= (steering_change ** 2) * 1.0
        self.last_steering = steering

        # 5. BRAKING PENALTY (Discourage unnecessary braking on open track)
        brake_input = action[1]
        if brake_input > 0.01:
            if is_grounded and not ghost_is_braking:
                reward -= brake_input * 3.0
            else:
                reward -= brake_input * 0.05

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

        # Capture telemetry frame for run replay recording
        t = self.last_telemetry
        if t and t.get('IsSpawned', False):
            self.current_episode_frames.append({
                'p': [round(float(t['Position']['x']), 3), round(float(t['Position']['y']), 3), round(float(t['Position']['z']), 3)],
                'r': [round(float(t['Rotation']['x']), 4), round(float(t['Rotation']['y']), 4), round(float(t['Rotation']['z']), 4), round(float(t['Rotation']['w']), 4)],
                's': round(float(t['Speed']), 2),
                'a': round(float(action[2]), 2),
                'b': round(float(action[1]), 2),
                'steer': round(float(action[0]), 2)
            })

        obs = self._get_obs()
        reward = self._calculate_reward(obs, action)
        self.episode_reward += reward
        
        if self.last_ghost_index > self.global_max_ghost_index:
            self.global_max_ghost_index = self.last_ghost_index
        
        # Stuck / Slow Crawl Detection (Only check after warmup period: steps > 80 ~1.6s)
        speed = obs[6]
        terminated = False
        termination_reason = "None"
        if self.steps_in_episode > 80 and speed < 5.0:
            if self.stuck_start_time is None:
                self.stuck_start_time = time.time()
            elif time.time() - self.stuck_start_time > 8.0:
                termination_reason = "Stuck (Speed < 5.0 for 8s)"
                reward -= 150.0
                self.episode_reward += (-150.0)
                msg = f"[RESET] Reason: {termination_reason} | Final Reward: {self.episode_reward:.2f}"
                print(msg)
                append_training_log(msg)
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
            msg = f"[STATUS] Time: {int(total_time)}s | Ep Steps: {self.steps_in_episode} | Ep Reward: {self.episode_reward:.2f}"
            print(msg)
            append_training_log(msg)
            self.last_log_time = now

        # Terminal conditions
        if not terminated:
            if getattr(self, 'fallen_off', False):
                termination_reason = "Veered off track (>15m from line)" if getattr(self, 'veered_off', False) else "Fell off track (>15m below line)"
                reward -= 150.0
                self.episode_reward += (-150.0)
                msg = f"[RESET] Reason: {termination_reason} | Final Reward: {self.episode_reward:.2f}"
                print(msg)
                append_training_log(msg)
                terminated = True
            elif not self.last_telemetry.get('IsSpawned', False) and self.steps_in_episode > 10:
                termination_reason = self.last_telemetry.get('ResetReason', 'Unknown')
                terminal_bonus = 5000.0 if termination_reason == "Finished" else -150.0
                reward += terminal_bonus
                self.episode_reward += terminal_bonus
                msg = f"[RESET] Reason: {termination_reason} | Final Reward: {self.episode_reward:.2f}"
                print(msg)
                append_training_log(msg)
                terminated = True
                
            if self.steps_in_episode > 15000: 
                termination_reason = "Step Limit Reached"
                msg = f"[RESET] Reason: {termination_reason} | Final Reward: {self.episode_reward:.2f}"
                print(msg)
                append_training_log(msg)
                terminated = True

        if terminated:
            self._save_episode_run(termination_reason)
        
        return obs, reward, terminated, False, {}

    def _save_episode_run(self, reason):
        """Saves completed episode trajectory in standard ghost JSON format for replay."""
        if not self.current_episode_frames or len(self.current_episode_frames) < 15:
            self.current_episode_frames = []
            return
            
        level_hash = self.current_level_hash or "UnknownLevel"
        track_runs_dir = os.path.join(self.runs_dir, level_hash)
        os.makedirs(track_runs_dir, exist_ok=True)
        
        timestamp = int(time.time())
        safe_reason = re.sub(r'[^a-zA-Z0-9_-]', '_', reason)[:20]
        filename = f"run_{timestamp}_inst{self.instance_id}_rew{int(self.episode_reward)}_{safe_reason}.json"
        filepath = os.path.join(track_runs_dir, filename)
        
        data = {
            "LevelHash": str(level_hash),
            "FrameCount": int(len(self.current_episode_frames)),
            "EpisodeReward": round(float(self.episode_reward), 2),
            "EpisodeSteps": int(self.steps_in_episode),
            "TerminationReason": str(reason),
            "FurthestGhostIndex": int(self.last_ghost_index),
            "Frames": self.current_episode_frames
        }
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, default=json_numpy_default)
        except Exception as e:
            print(f"Error saving run recording: {e}")
            
        self.current_episode_frames = []

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.steps_in_episode = 0
        
        # Always spawn at standard starting grid
        spawn_index = -1
        self.last_ghost_index = 0
        self.max_ghost_index = 0
        self.last_steering = 0.0
        self.episode_reward = 0.0
        self.stuck_start_time = None
        self.current_episode_frames = []
        
        print(f"\n--- NEW RACE STARTING (Starting Grid | Furthest: {self.global_max_ghost_index}) ---")
        self._send_input(0.0, 0.0, 0.0, reset=True, spawn_index=spawn_index)
        
        # Initial startup: wait for car to spawn and load ghost data once
        if self.last_telemetry is None or self.ghost_frames is None:
            self.telemetry_socket.settimeout(0.5)
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
                    time.sleep(0.01)
                except KeyboardInterrupt:
                    print("\nReset interrupted by user.")
                    raise
            else:
                print("Reset timed out after 30 seconds. Car may not be spawned.")
                
        # Flush socket so subsequent steps get fresh telemetry
        self.telemetry_socket.settimeout(0.0)
        try:
            while True: self.telemetry_socket.recv(8192)
        except Exception: pass
        self.telemetry_socket.settimeout(0.5)

        return self._get_obs(), {}

    def save_time(self):
        """Persists total cumulative training time to disk."""
        if self.instance_id == 0:
            session_delta = max(0.0, time.time() - self.start_session_time)
            total = self.accumulated_time + session_delta
            try:
                with open(self.time_file, "w") as f:
                    f.write(f"{total:.1f}")
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
        input_data = {
            "p": [[0,0,0]]*4,
            "t": round(float(total_time), 1),
            "rew": round(float(self.episode_reward), 1)
        }
        msg = header + json.dumps(input_data, default=json_numpy_default).encode('utf-8')
        try: self.input_socket.sendto(msg, (self.host, self.input_port))
        except Exception: pass

using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using System;
using System.IO;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using ZeepSDK.Racing;
using ZeepSDK.Level;
using Newtonsoft.Json;
using System.Reflection;
using Zeepkist.Ai.GtrClient;
using Zeepkist.Ai.GtrClient.Models;

namespace Zeepkist.Ai
{
    [BepInPlugin(MyPluginInfo.PLUGIN_GUID, MyPluginInfo.PLUGIN_NAME, MyPluginInfo.PLUGIN_VERSION)]
    [BepInDependency("ZeepSDK")]
    public class Plugin : BaseUnityPlugin
    {
        private Harmony harmony;

        public static ConfigEntry<bool> EnableAi { get; private set; }
        public static ConfigEntry<bool> ShowGhostPath { get; private set; }
        public static ConfigEntry<float> GameSpeed { get; private set; }
        public static ConfigEntry<int> TelemetryPort { get; private set; }
        public static ConfigEntry<int> InputPort { get; private set; }
        public static ConfigEntry<int> PointsTcpPort { get; private set; }
        public static ConfigEntry<bool> ShowEyesightLines { get; private set; }
        public static ConfigEntry<bool> ShowCpHomingLine { get; private set; }
        public static ConfigEntry<float> EyesightLineWidth { get; private set; }
        public static ConfigEntry<float> CpHomingLineWidth { get; private set; }

        private static UdpClient telemetryClient;
        private static IPEndPoint telemetryEndPoint;
        private static UdpClient inputServer;
        private static IPEndPoint inputEndPoint;
        private static TcpListener pointsTcpListener;

        public static AiInput CurrentInput { get; private set; } = new AiInput();
        public static New_ControlCar playerCar = null;
        private static string currentLevelHash = "Unknown";
        private static GhostVisualizer visualizer = null;
        private static RaycastVisualizer rayVisualizer = null;
        private static TargetVisualizer targetVisualizer = null;
        private static string lastResetReason = "None";
        private static bool checkpointReached = false;
        private static CheckpointHomingVisualizer homingVisualizer = null;

        private static GtrClient.GtrClient gtrClient;
        private static List<GhostFrame> cachedFrames = null;
        private static string cachedHash = "";
        private static List<BlockTriggerFinishOrCheckpoint> currentCheckpoints = new List<BlockTriggerFinishOrCheckpoint>();
        private static BlockTriggerFinishOrCheckpoint currentFinish = null;
        private static int nextCheckpointIndex = 0;
        private static int pendingSpawnIndex = -1;
        private static float[][] latestTargetPositions = null;
        private static readonly object targetLock = new object();
        private static BepInEx.Logging.ManualLogSource staticLogger;

        private static bool ghostLoaded = false;
        private static bool ghostReady = false;
        private static byte[] currentGhostBinary = null;
        private static readonly object ghostLock = new object();
        private static int inputPacketCount = 0;
        private static DateTime lastInputTime = DateTime.MinValue;

        private void Awake()
        {
            staticLogger = Logger;
            Logger.LogInfo("[AI_DEBUG] === Plugin.Awake() STARTING ===");
            harmony = new Harmony(MyPluginInfo.PLUGIN_GUID);
            harmony.PatchAll();

            EnableAi = Config.Bind<bool>("AI", "Enable AI control", false);
            GameSpeed = Config.Bind<float>("AI", "Game Speed Multiplier", 1.0f);
            ShowGhostPath = Config.Bind<bool>("Visuals", "Show GTR Ghost Path", true);
            TelemetryPort = Config.Bind<int>("Network", "Telemetry Port", 9090);
            InputPort = Config.Bind<int>("Network", "Input Port", 9091);
            PointsTcpPort = Config.Bind<int>("Network", "Ghost Points TCP Port", 9092);

            ShowEyesightLines = Config.Bind<bool>("Visuals", "Show Eyesight Lines", true);
            ShowCpHomingLine = Config.Bind<bool>("Visuals", "Show CP Homing Line", true);
            EyesightLineWidth = Config.Bind<float>("Visuals", "Eyesight Line Width", 0.05f);
            CpHomingLineWidth = Config.Bind<float>("Visuals", "CP Homing Line Width", 0.20f);

            gtrClient = new GtrClient.GtrClient(Logger);

            RacingApi.PassedCheckpoint += (time) => {
                checkpointReached = true;
            };

            RacingApi.PlayerSpawned += () => {
                nextCheckpointIndex = 0;
                InitializeCheckpoints();
                if (visualizer == null) {
                    GameObject vizObj = new GameObject("AI_GhostVisualizer");
                    visualizer = vizObj.AddComponent<GhostVisualizer>();
                }
                if (rayVisualizer == null) {
                    GameObject rayObj = new GameObject("AI_RayVisualizer");
                    rayVisualizer = rayObj.AddComponent<RaycastVisualizer>();
                }
                if (targetVisualizer == null) {
                    GameObject targetObj = new GameObject("AI_TargetVisualizer");
                    targetVisualizer = targetObj.AddComponent<TargetVisualizer>();
                }
                if (homingVisualizer == null) {
                    GameObject homingObj = new GameObject("AI_CheckpointHomingVisualizer");
                    homingVisualizer = homingObj.AddComponent<CheckpointHomingVisualizer>();
                }

                playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                if (pendingSpawnIndex >= 0) {
                    int spawnIdx = pendingSpawnIndex;
                    pendingSpawnIndex = -1;
                    UnityMainThreadDispatcher.Instance().Enqueue(() => {
                        TeleportCar(playerCar, spawnIdx);
                        UpdateNextCheckpointIndex();
                    });
                }
                string newHash = LevelApi.CurrentHash ?? LevelApi.CurrentLevel.UID;
                lastResetReason = "None";
                
                if (newHash != currentLevelHash || cachedFrames == null) {
                    Logger.LogInfo($"[AI_DEBUG] Level setup: Hash={newHash}, CacheReady={cachedFrames != null}. Fetching ghost.");
                    currentLevelHash = newHash;
                    ghostLoaded = false;
                    lock (ghostLock) { ghostReady = false; currentGhostBinary = null; }
                    cachedFrames = null;
                    cachedHash = "";
                    Task.Run(() => FetchAndProcessGhost(currentLevelHash));
                } else {
                    lock (ghostLock) { ghostReady = true; }
                    if (visualizer != null && ShowGhostPath.Value && cachedFrames != null) {
                        visualizer.UpdateLine(cachedFrames.Select(f => f.Position).ToList());
                    }
                }
            };

            RacingApi.Crashed += (reason) => { playerCar = null; lastResetReason = "Crashed: " + reason; };
            RacingApi.CrossedFinishLine += (time) => { playerCar = null; lastResetReason = "Finished"; };
            RacingApi.WheelBroken += () => { playerCar = null; lastResetReason = "Wheel Broken"; };

            SetupNetwork();
            Logger.LogInfo($"[AI_DEBUG] Plugin fully initialized!");
        }

        private async Task FetchAndProcessGhost(string hash)
        {
            if (hash == "Unknown") return;
            try {
                Logger.LogInfo($"[AI_DEBUG] Fetching best ghost for {hash}...");
                string url = await gtrClient.GetBestGhostUrl(hash);
                if (string.IsNullOrEmpty(url)) {
                    Logger.LogError($"[AI_DEBUG] No ghost URL found for {hash}. AI tracking will be disabled.");
                    return;
                }
                Logger.LogInfo($"[AI_DEBUG] Downloading/Parsing ghost: {url}");
                List<GhostFrame> frames = await gtrClient.DownloadAndParseGhost(url);
                if (frames == null) { Logger.LogError("[AI_DEBUG] Ghost parsing failed (returned null)."); return; }

                cachedFrames = frames;
                cachedHash = hash;
                Logger.LogInfo($"[AI_DEBUG] Successfully processed {frames.Count} points. Updating visualizer.");

                UnityMainThreadDispatcher.Instance().Enqueue(() => { 
                    if (visualizer != null && ShowGhostPath.Value) {
                        visualizer.UpdateLine(frames.Select(f => f.Position).ToList()); 
                    }
                    InitializeCheckpoints();
                });
                PrepareGhostBinary(frames, hash);
                Logger.LogInfo("[AI_DEBUG] ghostReady is now TRUE.");
            } catch (Exception ex) {
                Logger.LogError($"[AI_DEBUG] Critical error in FetchAndProcessGhost: {ex.Message}");
            }
        }

        private void SetupNetwork()
        {
            try {
                telemetryClient = new UdpClient();
                telemetryClient.Client.SendBufferSize = 65536;
                telemetryEndPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), TelemetryPort.Value);

                inputServer = new UdpClient(InputPort.Value);
                inputServer.Client.ReceiveBufferSize = 65536;
                inputEndPoint = new IPEndPoint(IPAddress.Any, InputPort.Value);
                
                // Start dedicated background thread for receiving inputs
                Thread receiveThread = new Thread(InputReceiverLoop);
                receiveThread.IsBackground = true;
                receiveThread.Start();

                pointsTcpListener = new TcpListener(IPAddress.Any, PointsTcpPort.Value);
                pointsTcpListener.Start();
                Logger.LogInfo($"[AI_DEBUG] TCP Points Server started on port {PointsTcpPort.Value}");
                
                Task.Run(async () => {
                    while (true) {
                        try {
                            using (TcpClient client = await pointsTcpListener.AcceptTcpClientAsync())
                            using (NetworkStream stream = client.GetStream()) {
                                byte[] dataToSend = null;
                                lock (ghostLock) { dataToSend = currentGhostBinary; }
                                if (dataToSend != null) {
                                    byte[] sizeBytes = BitConverter.GetBytes(dataToSend.Length);
                                    await stream.WriteAsync(sizeBytes, 0, 4);
                                    await stream.WriteAsync(dataToSend, 0, dataToSend.Length);
                                    Logger.LogInfo($"[AI_DEBUG] Sent {dataToSend.Length} bytes to Python via TCP.");
                                    ghostLoaded = true;
                                } else { Logger.LogWarning("[AI_DEBUG] Python connected but no ghost data is ready yet."); }
                            }
                        } catch (Exception ex) {
                            Logger.LogError($"[AI_DEBUG] TCP Server Loop Error: {ex.Message}");
                            await Task.Delay(1000);
                        }
                    }
                });
            } catch (Exception ex) { Logger.LogError($"AI Network Setup Error: {ex.Message}"); }
        }

        private static void InputReceiverLoop()
        {
            IPEndPoint remoteEP = new IPEndPoint(IPAddress.Any, InputPort.Value);
            staticLogger.LogInfo($"[AI_DEBUG] Dedicated Input Receiver Thread started on port {InputPort.Value}");
            
            while (true)
            {
                try
                {
                    if (inputServer == null)
                    {
                        Thread.Sleep(100);
                        continue;
                    }
                    
                    byte[] bytes = inputServer.Receive(ref remoteEP);
                    if (bytes != null && bytes.Length >= 18)
                    {
                        lastInputTime = DateTime.Now;
                        using (MemoryStream ms = new MemoryStream(bytes))
                        using (BinaryReader reader = new BinaryReader(ms))
                        {
                            float steer = reader.ReadSingle();
                            float brake = reader.ReadSingle();
                            float arms = reader.ReadSingle();
                            bool reset = reader.ReadBoolean();
                            bool reqGhost = reader.ReadBoolean();
                            int spawnIdx = reader.ReadInt32();

                            CurrentInput.Steering = steer;
                            CurrentInput.Brake = brake;
                            CurrentInput.ArmsUp = arms;
                            CurrentInput.Reset = reset;
                            CurrentInput.RequestGhost = reqGhost;
                            CurrentInput.SpawnIndex = spawnIdx;
                            
                            inputPacketCount++;
                            if (inputPacketCount % 500 == 0)
                            {
                                staticLogger.LogInfo($"[AI_DEBUG] Recv Input: Steer={steer:F2}, Brake={brake:F2}, Arms={arms:F2}, SpawnIndex={spawnIdx}");
                            }

                            if (bytes.Length > 18)
                            {
                                string json = Encoding.UTF8.GetString(bytes, 18, bytes.Length - 18);
                                var data = JsonConvert.DeserializeObject<JsonInputData>(json);
                                if (data != null)
                                {
                                    lock (targetLock) { latestTargetPositions = data.p; }
                                    CurrentInput.TrainingTime = data.t;
                                }
                            }
                        }
                    }
                }
                catch (SocketException ex)
                {
                    if (ex.SocketErrorCode == SocketError.Interrupted || ex.SocketErrorCode == SocketError.ConnectionReset)
                    {
                        // UDP port unreachable/closed, ignore
                    }
                    else
                    {
                        staticLogger.LogError($"[AI_DEBUG] Input Socket Exception: {ex.Message}");
                        Thread.Sleep(100);
                    }
                }
                catch (Exception ex)
                {
                    staticLogger.LogError($"[AI_DEBUG] Input Receiver Thread error: {ex.Message}");
                    Thread.Sleep(100);
                }
            }
        }

        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.F9)) {
                EnableAi.Value = !EnableAi.Value;
                Logger.LogInfo($"[AI_DEBUG] AI CONTROL: {(EnableAi.Value ? "ENABLED" : "DISABLED")}");
                if (!EnableAi.Value) Time.timeScale = 1.0f;
            }

            if (EnableAi.Value && Input.GetKeyDown(KeyCode.F10)) {
                if (GameSpeed.Value == 1.0f) GameSpeed.Value = 1.5f;
                else if (GameSpeed.Value == 1.5f) GameSpeed.Value = 2.0f;
                else if (GameSpeed.Value == 2.0f) GameSpeed.Value = 3.0f;
                else GameSpeed.Value = 1.0f;
                Logger.LogInfo($"[AI_DEBUG] GAME SPEED: {GameSpeed.Value}x");
            }

            if (latestTargetPositions != null && targetVisualizer != null) {
                float[][] posToUpdate = null;
                lock (targetLock) { posToUpdate = latestTargetPositions; latestTargetPositions = null; }
                if (posToUpdate != null) targetVisualizer.UpdateTargets(posToUpdate);
            }
        }


        private void FixedUpdate()
        {
            if (!EnableAi.Value) {
                if (Time.timeScale != 1.0f) Time.timeScale = 1.0f;
                return;
            }

            if (Time.timeScale != GameSpeed.Value) {
                Time.timeScale = GameSpeed.Value;
            }

            // Heartbeat: If Python pauses (training), hold last steering but don't reset.
            bool isPaused = (DateTime.Now - lastInputTime).TotalMilliseconds > 500;

            if (CurrentInput != null && CurrentInput.Reset && !isPaused) {
                if (PlayerManager.Instance?.currentMaster != null) {
                    pendingSpawnIndex = CurrentInput.SpawnIndex;
                    PlayerManager.Instance.currentMaster.RestartLevel();
                    CurrentInput.Reset = false; playerCar = null;
                }
            }
            UpdateNextCheckpointIndex();
            SendTelemetry();
        }

        private void SendTelemetry()
        {
            try {
                using (MemoryStream ms = new MemoryStream())
                using (BinaryWriter writer = new BinaryWriter(ms)) {
                    if (playerCar != null && playerCar.gameObject != null && playerCar.rb != null) {
                        var transform = playerCar.transform;
                        float[] rayDistances = new float[75];
                        
                        // 3 Layers: Low (-15 deg), Mid (0 deg), High (+15 deg)
                        for (int layer = 0; layer < 3; layer++) {
                            float pitch = -15f + (layer * 15f);
                            for (int i = 0; i < 25; i++) {
                                int idx = (layer * 25) + i;
                                float yaw = -60f + (i * (120f / 24f));
                                // Make direction truly local to the car
                                Vector3 localDir = Quaternion.Euler(pitch, yaw, 0) * Vector3.forward;
                                Vector3 dir = transform.TransformDirection(localDir);
                                float range = Mathf.Lerp(100f, 20f, Mathf.Abs(yaw) / 60f);
                                rayDistances[idx] = GetSphereCast(dir, range, idx);
                            }
                        }

                        bool isSlipping = false;
                        float friction = 0.0f;
                        bool isGrounded = false;
                        if (playerCar.wheels != null) {
                            isSlipping = playerCar.wheels.Any(x => x != null && x.IsGrounded() && x.IsSlipping());
                            var grounded = playerCar.wheels.FirstOrDefault(x => x != null && x.IsGrounded());
                            if (grounded != null) {
                                isGrounded = true;
                                friction = 1.0f;
                                if (grounded.GetCurrentSurface()?.physics != null)
                                    friction = grounded.GetCurrentSurface().physics.frictionFront;
                            }
                        }

                        // Ground Normal Sensor
                        Vector3 groundNormal = Vector3.up;
                        if (Physics.Raycast(transform.position + Vector3.up * 0.5f, Vector3.down, out RaycastHit groundHit, 3.0f)) {
                            groundNormal = groundHit.normal;
                        }

                        // Checkpoint Direction and Relative Position
                        Vector3 nextCpDir = transform.forward;
                        Vector3 relCpPos = Vector3.zero;
                        
                        Vector3 targetPos = Vector3.zero;
                        bool hasTarget = false;

                        if (nextCheckpointIndex < currentCheckpoints.Count && currentCheckpoints[nextCheckpointIndex] != null) {
                            targetPos = currentCheckpoints[nextCheckpointIndex].transform.position;
                            hasTarget = true;
                        } else if (currentFinish != null) {
                            targetPos = currentFinish.transform.position;
                            hasTarget = true;
                        }

                        if (hasTarget) {
                            nextCpDir = (targetPos - transform.position).normalized;
                            relCpPos = transform.InverseTransformPoint(targetPos);
                            
                            if (homingVisualizer != null) {
                                homingVisualizer.UpdateHoming(transform.position + transform.up * 1.0f, targetPos);
                            }
                        }

                        writer.Write(Time.time);
                        writer.Write(transform.position.x); writer.Write(transform.position.y); writer.Write(transform.position.z);
                        writer.Write(transform.rotation.x); writer.Write(transform.rotation.y); writer.Write(transform.rotation.z); writer.Write(transform.rotation.w);
                        writer.Write(playerCar.rb.velocity.x); writer.Write(playerCar.rb.velocity.y); writer.Write(playerCar.rb.velocity.z);
                        writer.Write(playerCar.rb.angularVelocity.x); writer.Write(playerCar.rb.angularVelocity.y); writer.Write(playerCar.rb.angularVelocity.z);
                        writer.Write(playerCar.rb.velocity.magnitude);
                        writer.Write(true); writer.Write(ghostLoaded); writer.Write(ghostReady); writer.Write(checkpointReached);
                        foreach (float r in rayDistances) writer.Write(r);
                        writer.Write(isSlipping);
                        writer.Write(isGrounded);
                        writer.Write(friction);
                        
                        // New Physics Data
                        writer.Write(groundNormal.x); writer.Write(groundNormal.y); writer.Write(groundNormal.z);
                        writer.Write(nextCpDir.x); writer.Write(nextCpDir.y); writer.Write(nextCpDir.z);
                        // Add relative position for the brain
                        writer.Write(relCpPos.x); writer.Write(relCpPos.y); writer.Write(relCpPos.z);

                        writer.Write(currentLevelHash); writer.Write(lastResetReason);
                        checkpointReached = false;
                    } else {
                        writer.Write(Time.time);
                        writer.Write(0f); writer.Write(0f); writer.Write(0f);
                        writer.Write(0f); writer.Write(0f); writer.Write(0f); writer.Write(1f);
                        writer.Write(0f); writer.Write(0f); writer.Write(0f);
                        writer.Write(0f); writer.Write(0f); writer.Write(0f);
                        writer.Write(0f);
                        writer.Write(false); writer.Write(ghostLoaded); writer.Write(ghostReady); writer.Write(false);
                        for (int i = 0; i < 75; i++) writer.Write(0f);
                        writer.Write(false);
                        writer.Write(false);
                        writer.Write(1.0f);
                        writer.Write(0f); writer.Write(1f); writer.Write(0f); // Ground Normal Up
                        writer.Write(0f); writer.Write(0f); writer.Write(1f); // CP Forward
                        writer.Write(0f); writer.Write(0f); writer.Write(0f); // CP Rel Pos
                        writer.Write(currentLevelHash); writer.Write(lastResetReason);
                    }
                    byte[] bytes = ms.ToArray();
                    Task.Run(() => {
                        try { telemetryClient.Send(bytes, bytes.Length, telemetryEndPoint); } catch { }
                    });
                }
            } catch { }
        }

        private float GetSphereCast(Vector3 direction, float maxDist, int index = -1)
        {
            if (playerCar == null) return maxDist;
            Vector3 origin = playerCar.transform.position + playerCar.transform.up * 1.0f;
            RaycastHit hit;
            float startOffset = 2.0f;
            float dist = maxDist;
            bool isObstacle = false;
            
            // Ignore the player car layer
            int layerMask = ~(1 << playerCar.gameObject.layer);
            
            Vector3 castOrigin = origin + direction * startOffset;
            if (Physics.SphereCast(castOrigin, 0.75f, direction, out hit, maxDist - startOffset, layerMask)) {
                dist = startOffset + hit.distance;
                if (Mathf.Abs(hit.normal.y) < 0.8f) { isObstacle = true; }
            }
            if (rayVisualizer != null && index >= 0) rayVisualizer.UpdateRay(index, origin, origin + direction * dist, isObstacle);
            return dist;
        }

        private static int GetClosestGhostFrameIndex(Vector3 pos)
        {
            if (cachedFrames == null || cachedFrames.Count == 0) return 0;
            int closestIdx = 0;
            float minDist = float.MaxValue;
            for (int i = 0; i < cachedFrames.Count; i++) {
                float dist = Vector3.Distance(cachedFrames[i].Position, pos);
                if (dist < minDist) {
                    minDist = dist;
                    closestIdx = i;
                }
            }
            return closestIdx;
        }

        private static void InitializeCheckpoints()
        {
            try {
                currentCheckpoints.Clear();
                currentFinish = null;

                var allTriggers = UnityEngine.Object.FindObjectsOfType<BlockTriggerFinishOrCheckpoint>();
                if (allTriggers == null || allTriggers.Length == 0) {
                    return;
                }

                List<BlockTriggerFinishOrCheckpoint> cps = new List<BlockTriggerFinishOrCheckpoint>();
                foreach (var trigger in allTriggers) {
                    if (trigger == null) continue;
                    if (trigger.isFinish) {
                        currentFinish = trigger;
                    } else {
                        cps.Add(trigger);
                    }
                }

                if (cachedFrames != null && cachedFrames.Count > 0) {
                    currentCheckpoints = cps.OrderBy(cp => GetClosestGhostFrameIndex(cp.transform.position)).ToList();
                } else {
                    currentCheckpoints = cps;
                }
            } catch { }
        }

        private static void TeleportCar(New_ControlCar car, int index)
        {
            if (car == null || cachedFrames == null || cachedFrames.Count == 0 || index < 0 || index >= cachedFrames.Count) return;
            try {
                var frame = cachedFrames[index];
                
                Vector3 dir = car.transform.forward;
                if (index < cachedFrames.Count - 1) {
                    dir = (cachedFrames[index + 1].Position - frame.Position).normalized;
                } else if (index > 0) {
                    dir = (frame.Position - cachedFrames[index - 1].Position).normalized;
                }
                
                car.rb.isKinematic = true;
                car.transform.position = frame.Position;
                car.transform.rotation = frame.Rotation;
                car.rb.isKinematic = false;
                
                car.rb.velocity = dir * frame.Speed;
                car.rb.angularVelocity = Vector3.zero;
                
                staticLogger.LogInfo($"[AI_DEBUG] Teleported car to index {index}. Position={frame.Position}, Speed={frame.Speed}");
            } catch (Exception ex) {
                staticLogger.LogError($"[AI_DEBUG] Error in TeleportCar: {ex.Message}");
            }
        }

        private static void UpdateNextCheckpointIndex()
        {
            if (playerCar == null || currentCheckpoints == null || currentCheckpoints.Count == 0) return;
            try {
                int carGhostIndex = GetClosestGhostFrameIndex(playerCar.transform.position);
                int nextCp = 0;
                for (int i = 0; i < currentCheckpoints.Count; i++) {
                    if (currentCheckpoints[i] != null) {
                        int cpGhostIndex = GetClosestGhostFrameIndex(currentCheckpoints[i].transform.position);
                        if (cpGhostIndex <= carGhostIndex) {
                            nextCp = i + 1;
                        }
                    }
                }
                nextCheckpointIndex = nextCp;
            } catch { }
        }

        public void PrepareGhostBinary(List<GhostFrame> frames, string levelHash)
        {
            // Send every 5th frame for precision in loops
            List<object> data_frames = new List<object>();
            for (int i = 0; i < frames.Count; i += 5) {
                data_frames.Add(new {
                    p = new float[] { frames[i].Position.x, frames[i].Position.y, frames[i].Position.z },
                    r = new float[] { frames[i].Rotation.x, frames[i].Rotation.y, frames[i].Rotation.z, frames[i].Rotation.w },
                    s = frames[i].Speed,
                    a = frames[i].ArmsUp,
                    b = frames[i].Braking
                });
            }

            var data = new { LevelHash = levelHash, FrameCount = data_frames.Count, Frames = data_frames };
            byte[] bytes = Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(data));
            lock (ghostLock) { currentGhostBinary = bytes; ghostReady = true; }
        }

        public void OnDestroy() { harmony?.UnpatchSelf(); inputServer?.Close(); telemetryClient?.Close(); pointsTcpListener?.Stop(); }

        [HarmonyPatch(typeof(New_ControlCar), "Update")]
        public static class New_ControlCar_Update_Patch {
            public static void Postfix(New_ControlCar __instance) {
                if (EnableAi.Value && CurrentInput != null && playerCar != null && __instance == playerCar) {
                    if (__instance.SteerAction2 != null) __instance.SteerAction2.axis = CurrentInput.Steering;
                    if (__instance.BrakeAction2 != null) { __instance.BrakeAction2.axis = CurrentInput.Brake; __instance.BrakeAction2.buttonHeld = CurrentInput.Brake > 0.5f; }
                    if (__instance.PitchBackwardAction2 != null) { __instance.PitchBackwardAction2.axis = CurrentInput.Brake; __instance.PitchBackwardAction2.buttonHeld = CurrentInput.Brake > 0.5f; }
                    if (__instance.ArmsUpAction2 != null) { __instance.ArmsUpAction2.axis = CurrentInput.ArmsUp; __instance.ArmsUpAction2.buttonHeld = CurrentInput.ArmsUp > 0.5f; }
                }
            }
        }
    }

    public class JsonInputData { public float[][] p; public float t; }

    public class UnityMainThreadDispatcher : MonoBehaviour {
        private static readonly Queue<Action> _executionQueue = new Queue<Action>();
        private static UnityMainThreadDispatcher _instance = null;
        public static UnityMainThreadDispatcher Instance() {
            if (_instance == null) {
                GameObject obj = new GameObject("UnityMainThreadDispatcher");
                _instance = obj.AddComponent<UnityMainThreadDispatcher>();
                DontDestroyOnLoad(obj);
            }
            return _instance;
        }
        public void Update() { lock (_executionQueue) { while (_executionQueue.Count > 0) _executionQueue.Dequeue().Invoke(); } }
        public void Enqueue(Action action) { lock (_executionQueue) _executionQueue.Enqueue(action); }
    }

    public class GhostVisualizer : MonoBehaviour {
        private LineRenderer line;
        private void Awake() {
            line = gameObject.AddComponent<LineRenderer>();
            line.useWorldSpace = true; line.startWidth = 1.0f; line.endWidth = 1.0f;
            line.material = new Material(Shader.Find("Sprites/Default"));
            line.startColor = Color.magenta; line.endColor = Color.magenta;
        }
        public void UpdateLine(List<Vector3> points) { line.positionCount = points.Count; line.SetPositions(points.ToArray()); }
    }

    public class RaycastVisualizer : MonoBehaviour {
        private LineRenderer[] lines;
        private static int debugLogCounter = 0;

        private void Awake() {
            lines = new LineRenderer[75];
            for (int i = 0; i < 75; i++) {
                GameObject obj = new GameObject($"Ray_{i}");
                obj.transform.SetParent(this.transform);
                lines[i] = obj.AddComponent<LineRenderer>();
                lines[i].useWorldSpace = true;
                lines[i].positionCount = 2;
                lines[i].material = new Material(Shader.Find("Sprites/Default"));
            }
        }
        public void UpdateRay(int idx, Vector3 start, Vector3 end, bool hit) {
            if (lines == null || idx < 0 || idx >= lines.Length || lines[idx] == null) return;
            lines[idx].enabled = Plugin.ShowEyesightLines.Value;
            if (!lines[idx].enabled) return;
            
            lines[idx].SetPositions(new Vector3[] { start, end });
            Color c;
            if (idx < 25) c = Color.cyan;
            else if (idx < 50) c = Color.yellow;
            else c = Color.magenta;
            
            if (hit) c = Color.red;
            lines[idx].startColor = c; lines[idx].endColor = c;

            if (idx == 0) {
                debugLogCounter++;
                if (debugLogCounter % 300 == 0) {
                    UnityEngine.Debug.Log($"[AI_DEBUG] Ray 0: Start={start}, End={end}, Length={Vector3.Distance(start, end):F2}, Hit={hit}, Enabled={lines[idx].enabled}");
                }
            }
        }
        private void Update() { 
            bool show = Plugin.playerCar != null && Plugin.EnableAi.Value && Plugin.ShowEyesightLines.Value;
            float width = Plugin.EyesightLineWidth.Value;
            foreach (var l in lines) {
                if (l != null) {
                    l.enabled = show;
                    l.startWidth = width;
                    l.endWidth = width;
                }
            }
        }
    }

    public class TargetVisualizer : MonoBehaviour {
        private GameObject[] markers;
        private void Awake() {
            markers = new GameObject[4];
            for (int i = 0; i < 4; i++) {
                markers[i] = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                markers[i].name = $"TargetMarker_{i}";
                markers[i].transform.SetParent(this.transform);
                markers[i].transform.localScale = Vector3.one * 1.5f;
                Destroy(markers[i].GetComponent<SphereCollider>());
                Renderer r = markers[i].GetComponent<Renderer>();
                r.material = new Material(Shader.Find("Hidden/Internal-Colored"));
                r.material.color = i == 0 ? Color.yellow : Color.cyan;
            }
        }
        public void UpdateTargets(float[][] positions) {
            if (positions == null) return;
            for (int i = 0; i < markers.Length; i++) {
                if (i < positions.Length) {
                    markers[i].SetActive(true);
                    markers[i].transform.position = new Vector3(positions[i][0], positions[i][1], positions[i][2]);
                } else markers[i].SetActive(false);
            }
        }
        private void Update() { if (Plugin.playerCar == null) foreach (var m in markers) if (m != null) m.SetActive(false); }
    }

    public class CheckpointHomingVisualizer : MonoBehaviour {
        private LineRenderer line;
        private void Awake() {
            line = gameObject.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.material = new Material(Shader.Find("Sprites/Default"));
            line.startColor = Color.yellow; line.endColor = Color.yellow;
            line.positionCount = 2;
        }
        public void UpdateHoming(Vector3 start, Vector3 end) {
            line.enabled = Plugin.ShowCpHomingLine.Value;
            if (!line.enabled) return;
            line.SetPositions(new Vector3[] { start, end });
        }
        private void Update() { 
            bool show = Plugin.playerCar != null && Plugin.EnableAi.Value && Plugin.ShowCpHomingLine.Value;
            line.enabled = show; 
            float width = Plugin.CpHomingLineWidth.Value;
            line.startWidth = width;
            line.endWidth = width;
        }
    }

    public class AiInput {
        public float Steering; public float Brake; public float ArmsUp; public bool Reset; public bool RequestGhost;
        public int SpawnIndex;
        public float[][] TargetPositions; public float TrainingTime;
    }
}

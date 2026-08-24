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
using System.Runtime.InteropServices;
using UnityEngine;
using UnityEngine.SceneManagement;
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

        [DllImport("user32.dll", EntryPoint = "SetWindowPos")]
        private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

        [DllImport("user32.dll", EntryPoint = "SetWindowText", CharSet = CharSet.Auto)]
        private static extern bool SetWindowText(IntPtr hWnd, string lpString);

        [DllImport("user32.dll", EntryPoint = "GetActiveWindow")]
        private static extern IntPtr GetActiveWindow();

        public static ConfigEntry<bool> EnableAi { get; private set; }
        public static ConfigEntry<bool> ShowGhostPath { get; private set; }
        public static ConfigEntry<float> GameSpeed { get; private set; }
        public static ConfigEntry<int> TelemetryPort { get; private set; }
        public static ConfigEntry<int> InputPort { get; private set; }
        public static ConfigEntry<int> PointsTcpPort { get; private set; }
        public static ConfigEntry<bool> ShowCpHomingLine { get; private set; }
        public static ConfigEntry<float> CpHomingLineWidth { get; private set; }

        private static volatile bool isShuttingDown = false;

        private static UdpClient telemetryClient;
        private static IPEndPoint telemetryEndPoint;
        private static UdpClient inputServer;
        private static IPEndPoint inputEndPoint;
        private static TcpListener pointsTcpListener;

        public static AiInput CurrentInput { get; private set; } = new AiInput();
        public static New_ControlCar playerCar = null;
        private static string currentLevelHash = "Unknown";
        private static GhostVisualizer visualizer = null;
        private static TargetVisualizer targetVisualizer = null;
        private static string lastResetReason = "None";
        private static bool checkpointReached = false;
        private static CheckpointHomingVisualizer homingVisualizer = null;
        private static LidarVisualizer lidarVisualizer = null;
        public static ConfigEntry<bool> ShowLidarRays;
        private static bool isRoundActive = false;
        private static bool isRewardFrozen = false;
        private static float lastFrozenReward = 0f;

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

        private static string autoTrackName = null;
        private static bool hasAutoLoaded = false;
        private static int winPosX = -1;
        private static int winPosY = -1;
        private static int winWidth = 960;
        private static int winHeight = 540;
        private static int instanceIndex = 1;

        private void Awake()
        {
            staticLogger = Logger;
            Logger.LogInfo("[AI_DEBUG] === Plugin.Awake() STARTING ===");

            // Parse Command-line arguments
            string[] args = Environment.GetCommandLineArgs();
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i].Equals("-autoTrack", StringComparison.OrdinalIgnoreCase))
                {
                    autoTrackName = args[i + 1];
                    Logger.LogInfo($"[AI_DEBUG] Auto-track requested via CLI: {autoTrackName}");
                }
                else if (args[i].Equals("-winX", StringComparison.OrdinalIgnoreCase))
                {
                    int.TryParse(args[i + 1], out winPosX);
                }
                else if (args[i].Equals("-winY", StringComparison.OrdinalIgnoreCase))
                {
                    int.TryParse(args[i + 1], out winPosY);
                }
                else if (args[i].Equals("-winW", StringComparison.OrdinalIgnoreCase))
                {
                    int.TryParse(args[i + 1], out winWidth);
                }
                else if (args[i].Equals("-winH", StringComparison.OrdinalIgnoreCase))
                {
                    int.TryParse(args[i + 1], out winHeight);
                }
                else if (args[i].Equals("-aiPortOffset", StringComparison.OrdinalIgnoreCase))
                {
                    if (int.TryParse(args[i + 1], out int offset))
                    {
                        instanceIndex = (offset / 10) + 1;
                    }
                }
            }

            if (winPosX >= 0 || args.Any(a => a.Equals("-windowed", StringComparison.OrdinalIgnoreCase) || a.Equals("-aiPortOffset", StringComparison.OrdinalIgnoreCase)))
            {
                StartCoroutine(EnforceWindowLayoutCoroutine());
            }

            harmony = new Harmony(MyPluginInfo.PLUGIN_GUID);
            harmony.PatchAll();

            EnableAi = Config.Bind<bool>("AI", "Enable AI control", false);
            GameSpeed = Config.Bind<float>("AI", "Game Speed Multiplier", 1.0f);
            ShowGhostPath = Config.Bind<bool>("Visuals", "Show GTR Ghost Path", true);
            TelemetryPort = Config.Bind<int>("Network", "Telemetry Port", 9090);
            InputPort = Config.Bind<int>("Network", "Input Port", 9091);
            PointsTcpPort = Config.Bind<int>("Network", "Ghost Points TCP Port", 9092);

            ShowCpHomingLine = Config.Bind<bool>("Visuals", "Show CP Homing Line", true);
            CpHomingLineWidth = Config.Bind<float>("Visuals", "CP Homing Line Width", 0.20f);
            ShowLidarRays = Config.Bind<bool>("Visuals", "Show Road-Aligned LIDAR Rays", true, "Renders visible road-aligned obstacle avoidance LIDAR beams");

            gtrClient = new GtrClient.GtrClient(Logger);

            SceneManager.sceneLoaded += OnSceneLoaded;

            RacingApi.PassedCheckpoint += (time) => {
                checkpointReached = true;
            };

            RacingApi.PlayerSpawned += () => {
                isRoundActive = true;
                nextCheckpointIndex = 0;
                InitializeCheckpoints();
                if (visualizer == null) {
                    GameObject vizObj = new GameObject("AI_GhostVisualizer");
                    visualizer = vizObj.AddComponent<GhostVisualizer>();
                }
                if (targetVisualizer == null) {
                    GameObject targetObj = new GameObject("AI_TargetVisualizer");
                    targetVisualizer = targetObj.AddComponent<TargetVisualizer>();
                }
                if (homingVisualizer == null) {
                    GameObject homingObj = new GameObject("AI_CheckpointHomingVisualizer");
                    homingVisualizer = homingObj.AddComponent<CheckpointHomingVisualizer>();
                }
                if (lidarVisualizer == null) {
                    GameObject lidarObj = new GameObject("AI_LidarVisualizer");
                    lidarVisualizer = lidarObj.AddComponent<LidarVisualizer>();
                }

                UnityMainThreadDispatcher.Instance().Enqueue(() => {
                    try {
                        if (PlayerManager.Instance?.currentMaster?.carSetups != null && PlayerManager.Instance.currentMaster.carSetups.Count > 0) {
                            playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                            staticLogger.LogInfo($"[AI_DEBUG] PlayerSpawned: Resolved playerCar successfully.");
                        } else {
                            staticLogger.LogWarning($"[AI_DEBUG] PlayerSpawned: carSetups is empty!");
                        }
                    } catch (Exception ex) {
                        staticLogger.LogError($"[AI_DEBUG] PlayerSpawned: Exception resolving playerCar: {ex.Message}");
                    }
                });

                string newHash = LevelApi.CurrentHash ?? LevelApi.CurrentLevel.UID;
                lastResetReason = "None";
                currentLevelHash = newHash;
                isRewardFrozen = false;
                
                if (EnableAi.Value)
                {
                    TriggerGhostFetch();
                }
            };

            RacingApi.Crashed += (reason) => { 
                playerCar = null; 
                isRoundActive = false; 
                isRewardFrozen = true; 
                lastFrozenReward = CurrentInput != null ? CurrentInput.Reward : 0f;
                lastResetReason = "Crashed: " + reason; 
            };
            RacingApi.CrossedFinishLine += (time) => { 
                playerCar = null; 
                isRoundActive = false; 
                isRewardFrozen = true; 
                lastFrozenReward = CurrentInput != null ? CurrentInput.Reward : 0f;
                lastResetReason = "Finished"; 
            };
            RacingApi.WheelBroken += () => { 
                playerCar = null; 
                isRoundActive = false; 
                isRewardFrozen = true; 
                lastFrozenReward = CurrentInput != null ? CurrentInput.Reward : 0f;
                lastResetReason = "Wheel Broken"; 
            };

            SetupNetwork();
            Logger.LogInfo($"[AI_DEBUG] Plugin fully initialized!");
        }

        private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            Logger.LogInfo($"[AI_SCENE] Scene Loaded: '{scene.name}' (BuildIndex: {scene.buildIndex})");
            if (!hasAutoLoaded && !string.IsNullOrEmpty(autoTrackName) && (scene.name.IndexOf("menu", StringComparison.OrdinalIgnoreCase) >= 0 || scene.name.IndexOf("main", StringComparison.OrdinalIgnoreCase) >= 0))
            {
                hasAutoLoaded = true;
                Logger.LogInfo($"[AI_AUTO] Detected Menu Scene '{scene.name}'. Auto-loading track '{autoTrackName}' in 1.5s...");
                StartCoroutine(AutoLoadTrackCoroutine(autoTrackName));
            }
        }

        private System.Collections.IEnumerator AutoLoadTrackCoroutine(string track)
        {
            EnableAi.Value = true;
            Logger.LogInfo($"[AI_AUTO] Initiating auto-load for track: '{track}'");

            LevelScriptableObject targetLevel = null;

            // Retry for up to 10 seconds to allow LevelManager to populate
            for (int attempt = 0; attempt < 20; attempt++)
            {
                yield return new WaitForSeconds(0.5f);

                if (LevelManager.Instance != null)
                {
                    LevelManager.Instance.TryGetLevel(track, out targetLevel);
                    if (targetLevel == null)
                    {
                        var all = LevelManager.Instance.GetAllLevels();
                        if (all != null)
                        {
                            targetLevel = all.FirstOrDefault(l => l != null && (
                                string.Equals(l.UID, track, StringComparison.OrdinalIgnoreCase) ||
                                string.Equals(l.name, track, StringComparison.OrdinalIgnoreCase) ||
                                string.Equals(l.Name, track, StringComparison.OrdinalIgnoreCase)));
                        }
                    }
                }

                if (targetLevel == null && PlayerManager.Instance?.allAdventureLevelsSO?.Levels != null)
                {
                    targetLevel = PlayerManager.Instance.allAdventureLevelsSO.Levels.FirstOrDefault(l => l != null && (
                        string.Equals(l.UID, track, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(l.name, track, StringComparison.OrdinalIgnoreCase) ||
                        string.Equals(l.Name, track, StringComparison.OrdinalIgnoreCase)));
                }

                if (targetLevel != null) break;
            }

            try
            {
                if (targetLevel != null)
                {
                    Logger.LogInfo($"[AI_AUTO] Resolved level '{targetLevel.Name}' (UID: {targetLevel.UID}). Preparing GlobalLevel and loading GameScene...");

                    var selectMenus = Resources.FindObjectsOfTypeAll<SelectNextLevelMenu>();
                    foreach (var m in selectMenus)
                    {
                        if (m != null && m.GlobalLevel != null)
                        {
                            m.GlobalLevel.Copy(targetLevel);
                        }
                    }

                    var allSOs = Resources.FindObjectsOfTypeAll<LevelScriptableObject>();
                    foreach (var so in allSOs)
                    {
                        if (so != null && (so.name == "GlobalLevel" || so.name.Contains("Global")))
                        {
                            so.Copy(targetLevel);
                        }
                    }

                    if (targetLevel is AdventureLevelScriptableObject adv)
                    {
                        if (PlayerManager.Instance != null) PlayerManager.Instance.adventureSelectedLevel = adv;
                    }
                    else if (PlayerManager.Instance != null)
                    {
                        PlayerManager.Instance.adventureSelectedLevel = null;
                    }

                    SceneManager.LoadScene("GameScene");
                    Logger.LogInfo("[AI_AUTO] SceneManager.LoadScene('GameScene') called successfully!");
                }
                else
                {
                    Logger.LogWarning($"[AI_AUTO] Could not resolve level for '{track}' after 10 seconds.");
                }
            }
            catch (Exception ex)
            {
                Logger.LogError($"[AI_AUTO] Failed to auto-load track '{track}': {ex.Message}");
            }
        }

        private System.Collections.IEnumerator EnforceWindowLayoutCoroutine()
        {
            yield return new WaitForSeconds(0.5f);
            try
            {
                if (Screen.fullScreen || Screen.width != winWidth || Screen.height != winHeight)
                {
                    Screen.SetResolution(winWidth, winHeight, FullScreenMode.Windowed);
                }
            }
            catch { }

            for (int i = 0; i < 15; i++)
            {
                yield return new WaitForSeconds(0.25f);
                try
                {
                    IntPtr hwnd = System.Diagnostics.Process.GetCurrentProcess().MainWindowHandle;
                    if (hwnd != IntPtr.Zero)
                    {
                        SetWindowText(hwnd, $"Zeepkist #{instanceIndex}");
                        if (winPosX >= 0 && winPosY >= 0)
                        {
                            SetWindowPos(hwnd, IntPtr.Zero, winPosX, winPosY, winWidth, winHeight, 0x0040);
                        }
                    }
                }
                catch { }
            }
        }

        private static async Task FetchAndProcessGhost(string hash)
        {
            if (hash == "Unknown") return;
            try {
                string url = await gtrClient.GetBestGhostUrl(hash);
                if (string.IsNullOrEmpty(url)) {
                    staticLogger?.LogError($"[AI_DEBUG] No ghost URL found for {hash}. AI tracking will be disabled.");
                    return;
                }
                staticLogger?.LogInfo($"[AI_DEBUG] Downloading/Parsing ghost: {url}");
                List<GhostFrame> frames = await gtrClient.DownloadAndParseGhost(url);
                if (frames == null) { staticLogger?.LogError("[AI_DEBUG] Ghost parsing failed (returned null)."); return; }

                cachedFrames = frames;
                cachedHash = hash;
                staticLogger?.LogInfo($"[AI_DEBUG] Successfully processed {frames.Count} points. Updating visualizer.");

                UnityMainThreadDispatcher.Instance().Enqueue(() => { 
                    if (visualizer != null && ShowGhostPath.Value) {
                        visualizer.UpdateLine(frames.Select(f => f.Position).ToList()); 
                    }
                    InitializeCheckpoints();
                });
                PrepareGhostBinary(frames, hash);
                staticLogger?.LogInfo("[AI_DEBUG] ghostReady is now TRUE.");
            } catch (Exception ex) {
                staticLogger?.LogError($"[AI_DEBUG] Critical error in FetchAndProcessGhost: {ex.Message}");
            }
        }

        private static void TriggerGhostFetch()
        {
            string newHash = LevelApi.CurrentHash ?? LevelApi.CurrentLevel?.UID ?? "Unknown";
            if (newHash != "Unknown" && (newHash != cachedHash || cachedFrames == null)) {
                staticLogger?.LogInfo($"[AI_DEBUG] Triggering ghost fetch for {newHash}...");
                cachedHash = newHash;
                ghostLoaded = false;
                lock (ghostLock) { ghostReady = false; currentGhostBinary = null; }
                cachedFrames = null;
                Task.Run(() => FetchAndProcessGhost(cachedHash));
            } else if (visualizer != null && ShowGhostPath.Value && cachedFrames != null) {
                visualizer.UpdateLine(cachedFrames.Select(f => f.Position).ToList());
            }
        }

        private void SetupNetwork()
        {
            try {
                // Support multi-instance command-line argument: -aiPortOffset 10
                int portOffset = 0;
                string[] args = Environment.GetCommandLineArgs();
                for (int i = 0; i < args.Length - 1; i++) {
                    if (args[i].Equals("-aiPortOffset", StringComparison.OrdinalIgnoreCase)) {
                        int.TryParse(args[i + 1], out portOffset);
                        break;
                    }
                }

                int telemPort = TelemetryPort.Value + portOffset;
                int inPort = InputPort.Value + portOffset;
                int ptsPort = PointsTcpPort.Value + portOffset;

                telemetryClient = new UdpClient();
                telemetryClient.Client.SendBufferSize = 65536;
                telemetryEndPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), telemPort);

                inputServer = new UdpClient(inPort);
                inputServer.Client.ReceiveBufferSize = 65536;
                inputEndPoint = new IPEndPoint(IPAddress.Any, inPort);
                
                Thread receiveThread = new Thread(InputReceiverLoop);
                receiveThread.IsBackground = true;
                receiveThread.Start();

                pointsTcpListener = new TcpListener(IPAddress.Any, ptsPort);
                pointsTcpListener.Start();
                Logger.LogInfo($"[AI_DEBUG] Network initialized (Telemetry: {telemPort}, Input: {inPort}, Points: {ptsPort})");
                
                Task.Run(async () => {
                    while (!isShuttingDown) {
                        try {
                            if (pointsTcpListener == null || isShuttingDown) break;
                            using (TcpClient client = await pointsTcpListener.AcceptTcpClientAsync())
                            using (NetworkStream stream = client.GetStream()) {
                                byte[] dataToSend = null;
                                lock (ghostLock) { dataToSend = currentGhostBinary; }
                                if (dataToSend == null) {
                                    staticLogger?.LogInfo("[AI_DEBUG] Python connected to TCP port but ghost not ready yet. Triggering fetch now...");
                                    TriggerGhostFetch();
                                    for (int wait = 0; wait < 30; wait++) {
                                        if (isShuttingDown) break;
                                        await Task.Delay(200);
                                        lock (ghostLock) { dataToSend = currentGhostBinary; }
                                        if (dataToSend != null) break;
                                    }
                                }

                                if (dataToSend != null && !isShuttingDown) {
                                    byte[] sizeBytes = BitConverter.GetBytes(dataToSend.Length);
                                    await stream.WriteAsync(sizeBytes, 0, 4);
                                    await stream.WriteAsync(dataToSend, 0, dataToSend.Length);
                                    staticLogger?.LogInfo($"[AI_DEBUG] Sent {dataToSend.Length} bytes to Python via TCP.");
                                    ghostLoaded = true;
                                } else if (!isShuttingDown) {
                                    staticLogger?.LogWarning("[AI_DEBUG] Python connected but ghost data could not be prepared.");
                                }
                            }
                        } catch (ObjectDisposedException) {
                            break;
                        } catch (Exception ex) {
                            if (isShuttingDown) break;
                            staticLogger?.LogError($"[AI_DEBUG] TCP Server Loop Error: {ex.Message}");
                            await Task.Delay(1000);
                        }
                    }
                });
            } catch (Exception ex) { Logger.LogError($"AI Network Setup Error: {ex.Message}"); }
        }

        private static bool IsAiActive()
        {
            return EnableAi.Value && (DateTime.Now - lastInputTime).TotalSeconds <= 10.0;
        }

        private void OnGUI()
        {
            if (!EnableAi.Value) return;

            GUI.color = Color.white;
            GUI.Box(new Rect(10, 10, 270, 130), "=== Zeepkist AI HUD ===");
            
            bool active = IsAiActive();
            GUI.Label(new Rect(20, 30, 250, 20), $"Status: {(active ? "<color=green>AI ACTIVE</color>" : "<color=yellow>STANDBY / MANUAL</color>")}");
            GUI.Label(new Rect(20, 50, 250, 20), $"Speed: {Time.timeScale:F1}x | Track: {currentLevelHash}");
            
            float displayReward = isRewardFrozen ? lastFrozenReward : (CurrentInput != null ? CurrentInput.Reward : 0f);
            string rewardColor = displayReward >= 0 ? "<color=#00FF66>" : "<color=#FF4444>";
            string rewardLabel = isRewardFrozen ? "Reward (FINAL)" : "Reward";
            GUI.Label(new Rect(20, 70, 250, 20), $"{rewardLabel}: {rewardColor}{displayReward:+0.0;-0.0;0.0}</color>");

            float steer = CurrentInput != null ? CurrentInput.Steering : 0f;
            float brake = CurrentInput != null ? CurrentInput.Brake : 0f;
            float arms = CurrentInput != null ? CurrentInput.ArmsUp : 0f;
            
            GUI.Label(new Rect(20, 90, 250, 20), $"Steer: {steer:+0.00;-0.00; 0.00} | Brake: {brake:F2} | Arms: {arms:F2}");

            int barLen = 18;
            int steerPos = Mathf.Clamp((int)((steer + 1f) * 0.5f * barLen), 0, barLen);
            char[] bar = new string('-', barLen).ToCharArray();
            bar[barLen / 2] = '|';
            bar[steerPos] = 'O';
            GUI.Label(new Rect(20, 108, 250, 20), $"[{new string(bar)}]");
        }

        private static void InputReceiverLoop()
        {
            IPEndPoint remoteEP = new IPEndPoint(IPAddress.Any, InputPort.Value);
            staticLogger?.LogInfo($"[AI_DEBUG] Dedicated Input Receiver Thread started on port {InputPort.Value}");
            
            while (!isShuttingDown)
            {
                try
                {
                    if (inputServer == null || isShuttingDown)
                    {
                        break;
                    }
                    
                    byte[] bytes = inputServer.Receive(ref remoteEP);
                    if (bytes != null && bytes.Length >= 18 && !isShuttingDown)
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
                            
                            if (reqGhost && !isShuttingDown)
                            {
                                TriggerGhostFetch();
                            }
                            
                            inputPacketCount++;
                            if (inputPacketCount % 500 == 0)
                            {
                                staticLogger?.LogInfo($"[AI_DEBUG] Recv Input: Steer={steer:F2}, Brake={brake:F2}, Arms={arms:F2}, SpawnIndex={spawnIdx}");
                            }

                            if (bytes.Length > 18)
                            {
                                string json = Encoding.UTF8.GetString(bytes, 18, bytes.Length - 18);
                                var data = JsonConvert.DeserializeObject<JsonInputData>(json);
                                if (data != null)
                                {
                                    lock (targetLock) { latestTargetPositions = data.p; }
                                    CurrentInput.TrainingTime = data.t;
                                    if (!isRewardFrozen)
                                    {
                                        CurrentInput.Reward = data.rew;
                                    }
                                }
                            }
                        }
                    }
                }
                catch (ObjectDisposedException)
                {
                    break;
                }
                catch (SocketException ex)
                {
                    if (isShuttingDown || ex.SocketErrorCode == SocketError.Interrupted || ex.SocketErrorCode == SocketError.ConnectionReset)
                    {
                        break;
                    }
                    staticLogger?.LogError($"[AI_DEBUG] Input Socket Exception: {ex.Message}");
                    Thread.Sleep(100);
                }
                catch (Exception ex)
                {
                    if (isShuttingDown) break;
                    staticLogger?.LogError($"[AI_DEBUG] Input Receiver Thread error: {ex.Message}");
                    Thread.Sleep(100);
                }
            }
        }

        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.F9)) {
                EnableAi.Value = !EnableAi.Value;
                Logger.LogInfo($"[AI_DEBUG] AI CONTROL: {(EnableAi.Value ? "ENABLED" : "DISABLED")}");
                if (!EnableAi.Value) {
                    Time.timeScale = 1.0f;
                } else {
                    TriggerGhostFetch();
                }
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

            // Heartbeat: If Python disconnects (>10s), pause reset commands
            bool isPaused = (DateTime.Now - lastInputTime).TotalSeconds > 10.0;

            if (CurrentInput != null && CurrentInput.Reset && !isPaused) {
                if (PlayerManager.Instance?.currentMaster != null) {
                    PlayerManager.Instance.currentMaster.RestartLevel();
                    CurrentInput.Reset = false; playerCar = null; isRoundActive = false;
                }
            }

            // Self-healing: Resolve playerCar if null or destroyed
            if (playerCar == null || playerCar.gameObject == null) {
                try {
                    if (PlayerManager.Instance?.currentMaster?.carSetups != null && PlayerManager.Instance.currentMaster.carSetups.Count > 0) {
                        var firstCc = PlayerManager.Instance.currentMaster.carSetups.First()?.cc;
                        if (firstCc != null && firstCc.gameObject != null && firstCc.rb != null) {
                            playerCar = firstCc;
                            isRoundActive = true;
                            isRewardFrozen = false;
                        }
                    }
                } catch { }
            }

            UpdateNextCheckpointIndex();
            SendTelemetry();
        }

        private void SendTelemetry()
        {
            try {
                using (MemoryStream ms = new MemoryStream())
                using (BinaryWriter writer = new BinaryWriter(ms)) {
                    if (playerCar != null && playerCar.gameObject != null && playerCar.rb != null && (CurrentInput == null || !CurrentInput.Reset)) {
                        var transform = playerCar.transform;
                        
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
                        writer.Write(isSlipping);
                        writer.Write(isGrounded);
                        writer.Write(friction);
                        
                        // New Physics Data
                        writer.Write(groundNormal.x); writer.Write(groundNormal.y); writer.Write(groundNormal.z);
                        writer.Write(nextCpDir.x); writer.Write(nextCpDir.y); writer.Write(nextCpDir.z);
                        // Add relative position for the brain
                        writer.Write(relCpPos.x); writer.Write(relCpPos.y); writer.Write(relCpPos.z);

                        writer.Write(currentLevelHash); writer.Write(lastResetReason);

                        // --- TRACK-SPLINE ALIGNED LIDAR SENSORS (Always points down the driving line) ---
                        Vector3 trackSplineForward = transform.forward;
                        if (cachedFrames != null && cachedFrames.Count > 1) {
                            int closestIdx = GetClosestGhostFrameIndex(transform.position);
                            int targetIdx = Mathf.Min(cachedFrames.Count - 1, closestIdx + 4);
                            if (targetIdx != closestIdx) {
                                Vector3 splineTan = (cachedFrames[targetIdx].Position - cachedFrames[closestIdx].Position).normalized;
                                if (splineTan.sqrMagnitude > 0.001f) trackSplineForward = splineTan;
                            }
                        }

                        Vector3 fwdOnGround = Vector3.ProjectOnPlane(trackSplineForward, groundNormal).normalized;
                        if (fwdOnGround.sqrMagnitude < 0.001f) fwdOnGround = trackSplineForward;
                        Vector3 lidarOrigin = transform.position + groundNormal * 0.35f;

                        // Compact beam angles (-16 to +16 deg) spanning 4.4m corridor at 8m max distance
                        float[] lidarAngles = new float[] { -16f, -8f, 0f, 8f, 16f };
                        Vector3[] lidarDirs = new Vector3[5];
                        float[] lidarDists = new float[5];
                        const float LidarMaxDist = 8.0f;
                        int raycastMask = ~LayerMask.GetMask("Ignore Raycast");

                        for (int r = 0; r < 5; r++) {
                            Quaternion rot = Quaternion.AngleAxis(lidarAngles[r], groundNormal);
                            Vector3 dir = rot * fwdOnGround;
                            lidarDirs[r] = dir;
                            if (Physics.Raycast(lidarOrigin, dir, out RaycastHit hit, LidarMaxDist, raycastMask, QueryTriggerInteraction.Ignore)) {
                                lidarDists[r] = hit.distance;
                            } else {
                                lidarDists[r] = LidarMaxDist;
                            }
                            writer.Write(lidarDists[r]);
                        }

                        if (lidarVisualizer != null) {
                            lidarVisualizer.UpdateBeams(lidarOrigin, lidarDirs, lidarDists, LidarMaxDist);
                        }

                        checkpointReached = false;
                    } else {
                        writer.Write(Time.time);
                        writer.Write(0f); writer.Write(0f); writer.Write(0f);
                        writer.Write(0f); writer.Write(0f); writer.Write(0f); writer.Write(1f);
                        writer.Write(0f); writer.Write(0f); writer.Write(0f);
                        writer.Write(0f); writer.Write(0f); writer.Write(0f);
                        writer.Write(0f);
                        writer.Write(false); writer.Write(ghostLoaded); writer.Write(ghostReady); writer.Write(false);
                        writer.Write(false);
                        writer.Write(false);
                        writer.Write(1.0f);
                        writer.Write(0f); writer.Write(1f); writer.Write(0f); // Ground Normal Up
                        writer.Write(0f); writer.Write(0f); writer.Write(1f); // CP Forward
                        writer.Write(0f); writer.Write(0f); writer.Write(0f); // CP Rel Pos
                        writer.Write(currentLevelHash); writer.Write(lastResetReason);
                        for (int r = 0; r < 5; r++) {
                            writer.Write(8.0f);
                        }
                    }
                    byte[] bytes = ms.ToArray();
                    try { telemetryClient.Send(bytes, bytes.Length, telemetryEndPoint); } catch { }
                }
            } catch { }
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

        public static void PrepareGhostBinary(List<GhostFrame> frames, string levelHash)
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

        private void OnApplicationQuit()
        {
            isShuttingDown = true;
            try { inputServer?.Close(); } catch { }
            try { telemetryClient?.Close(); } catch { }
            try { pointsTcpListener?.Stop(); } catch { }
        }

        public void OnDestroy()
        {
            isShuttingDown = true;
            try { inputServer?.Close(); } catch { }
            try { telemetryClient?.Close(); } catch { }
            try { pointsTcpListener?.Stop(); } catch { }
        }

        // =========================================================================
        // DIRECT INPUT PREFIX PATCHES (Bulletproof steering, braking, and arms-up)
        // =========================================================================

        [HarmonyPatch(typeof(New_ControlCar), "GetSteerActionButLimited")]
        public static class GetSteerActionButLimited_Patch {
            public static bool Prefix(New_ControlCar __instance, ref float __result) {
                if (EnableAi.Value && playerCar != null && __instance == playerCar && IsAiActive() && CurrentInput != null) {
                    __result = CurrentInput.Steering;
                    return false; // Skip original game computation, apply steering directly
                }
                return true;
            }
        }

        [HarmonyPatch(typeof(New_ControlCar), "GetBrakeAxis")]
        public static class GetBrakeAxis_Patch {
            public static bool Prefix(New_ControlCar __instance, ref float __result) {
                if (EnableAi.Value && playerCar != null && __instance == playerCar && IsAiActive() && CurrentInput != null) {
                    __result = CurrentInput.Brake;
                    return false;
                }
                return true;
            }
        }

        [HarmonyPatch(typeof(New_ControlCar), "GetBrakeHeld")]
        public static class GetBrakeHeld_Patch {
            public static bool Prefix(New_ControlCar __instance, ref bool __result) {
                if (EnableAi.Value && playerCar != null && __instance == playerCar && IsAiActive() && CurrentInput != null) {
                    __result = CurrentInput.Brake > 0.5f;
                    return false;
                }
                return true;
            }
        }

        [HarmonyPatch(typeof(New_ControlCar), "GetArmsUpAxis")]
        public static class GetArmsUpAxis_Patch {
            public static bool Prefix(New_ControlCar __instance, ref float __result) {
                if (EnableAi.Value && playerCar != null && __instance == playerCar && IsAiActive() && CurrentInput != null) {
                    __result = CurrentInput.ArmsUp;
                    return false;
                }
                return true;
            }
        }

        [HarmonyPatch(typeof(New_ControlCar), "GetArmsUpHeld")]
        public static class GetArmsUpHeld_Patch {
            public static bool Prefix(New_ControlCar __instance, ref bool __result) {
                if (EnableAi.Value && playerCar != null && __instance == playerCar && IsAiActive() && CurrentInput != null) {
                    __result = CurrentInput.ArmsUp > 0.5f;
                    return false;
                }
                return true;
            }
        }

        [HarmonyPatch(typeof(Steamworks.SteamClient), "RestartAppIfNecessary")]
        public static class SteamClient_RestartAppIfNecessary_Patch {
            public static bool Prefix(ref bool __result) {
                __result = false;
                return false; // Skip restart check so multiple instances don't quit
            }
        }

        [HarmonyPatch(typeof(SteamManager), "Awake")]
        public static class SteamManager_Awake_Patch {
            public static Exception Finalizer(Exception __exception) {
                if (__exception != null) {
                    staticLogger?.LogWarning($"[AI_DEBUG] Caught and handled SteamManager exception: {__exception.Message}");
                }
                return null;
            }
        }

        [HarmonyPatch(typeof(Instellingen), "ApplyGraphicsSettings")]
        public static class Instellingen_ApplyGraphicsSettings_Patch {
            public static bool Prefix(bool resolutionChanged) {
                string[] args = Environment.GetCommandLineArgs();
                if (winPosX >= 0 || args.Any(a => a.Equals("-aiPortOffset", StringComparison.OrdinalIgnoreCase) || a.Equals("-windowed", StringComparison.OrdinalIgnoreCase))) {
                    Screen.SetResolution(winWidth, winHeight, FullScreenMode.Windowed);
                    return false; // Skip enforcing user fullscreen settings on AI replicas
                }
                return true;
            }
        }

        [HarmonyPatch(typeof(PressAnyKeyToStartGame), "Start")]
        public static class PressAnyKeyToStartGame_Start_Patch {
            public static void Postfix(PressAnyKeyToStartGame __instance) {
                Plugin.staticLogger?.LogInfo($"[AI_AUTO] PressAnyKeyToStartGame detected! Loading target scene immediately...");
                string target = string.IsNullOrEmpty(__instance.nextLevel) ? "3D_MainMenu" : __instance.nextLevel;
                SceneManager.LoadScene(target);
            }
        }
    }

    public class JsonInputData { public float[][] p; public float t; public float rew; }

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
        private void Update() {
            if (line != null) {
                line.enabled = Plugin.EnableAi.Value && Plugin.ShowGhostPath.Value;
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
        private void Update() { 
            bool show = Plugin.playerCar != null && Plugin.EnableAi.Value;
            foreach (var m in markers) {
                if (m != null) m.SetActive(show);
            }
        }
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

    public class LidarVisualizer : MonoBehaviour {
        private LineRenderer[] lines;
        private static readonly Color HitColor = new Color(1f, 0.2f, 0.2f, 0.95f);   // Bright Red on barrier detection
        private static readonly Color ClearColor = new Color(0.1f, 1f, 0.4f, 0.45f); // Transparent Green on clear road

        private void Awake() {
            lines = new LineRenderer[5];
            for (int i = 0; i < 5; i++) {
                GameObject child = new GameObject($"LidarBeam_{i}");
                child.transform.SetParent(this.transform);
                LineRenderer lr = child.AddComponent<LineRenderer>();
                lr.useWorldSpace = true;
                lr.startWidth = 0.08f;
                lr.endWidth = 0.08f;
                lr.material = new Material(Shader.Find("Sprites/Default"));
                lr.startColor = ClearColor;
                lr.endColor = ClearColor;
                lines[i] = lr;
            }
        }

        public void UpdateBeams(Vector3 origin, Vector3[] rayDirs, float[] hitDists, float maxDist) {
            if (lines == null || rayDirs == null) return;
            bool enable = Plugin.EnableAi.Value && Plugin.ShowLidarRays.Value && Plugin.playerCar != null;
            for (int i = 0; i < lines.Length; i++) {
                if (lines[i] == null) continue;
                if (!enable || i >= rayDirs.Length) {
                    lines[i].enabled = false;
                    continue;
                }
                lines[i].enabled = true;
                lines[i].positionCount = 2;
                lines[i].SetPosition(0, origin);
                float d = (hitDists != null && i < hitDists.Length) ? hitDists[i] : maxDist;
                Vector3 endPos = origin + rayDirs[i] * d;
                lines[i].SetPosition(1, endPos);
                Color c = d < (maxDist - 0.5f) ? HitColor : ClearColor;
                lines[i].startColor = c;
                lines[i].endColor = c;
            }
        }

        private void Update() { 
            if (!Plugin.EnableAi.Value || !Plugin.ShowLidarRays.Value || Plugin.playerCar == null) {
                if (lines != null) {
                    foreach (var l in lines) if (l != null) l.enabled = false;
                }
            }
        }
    }

    public class AiInput {
        public float Steering; public float Brake; public float ArmsUp; public bool Reset; public bool RequestGhost;
        public int SpawnIndex;
        public float[][] TargetPositions; public float TrainingTime; public float Reward;
    }
}

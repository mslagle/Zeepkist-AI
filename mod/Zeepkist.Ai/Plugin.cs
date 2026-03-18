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
using System.Threading.Tasks;
using UnityEngine;
using ZeepSDK.Racing;
using ZeepSDK.Level;
using Newtonsoft.Json;
using System.Reflection;
using Zeepkist.Ai.GtrClient;

namespace Zeepkist.Ai
{
    [BepInPlugin(MyPluginInfo.PLUGIN_GUID, MyPluginInfo.PLUGIN_NAME, MyPluginInfo.PLUGIN_VERSION)]
    [BepInDependency("ZeepSDK")]
    public class Plugin : BaseUnityPlugin
    {
        private Harmony harmony;

        public static ConfigEntry<bool> EnableAi { get; private set; }
        public static ConfigEntry<bool> ShowGhostPath { get; private set; }
        public static ConfigEntry<int> TelemetryPort { get; private set; }
        public static ConfigEntry<int> InputPort { get; private set; }
        public static ConfigEntry<int> PointsTcpPort { get; private set; }

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

        private static GtrClient.GtrClient gtrClient;
        private static List<Vector3> cachedPoints = null;
        private static string cachedHash = "";
        private static bool isSendingPoints = false;
        private static float[][] latestTargetPositions = null;
        private static readonly object targetLock = new object();

        private static bool ghostLoaded = false;
        private static bool ghostReady = false;
        private static byte[] currentGhostBinary = null;
        private static readonly object ghostLock = new object();
        private static int inputPacketCount = 0;
        private static DateTime lastInputTime = DateTime.MinValue;

        private void Awake()
        {
            Logger.LogInfo("[AI_DEBUG] === Plugin.Awake() STARTING ===");
            harmony = new Harmony(MyPluginInfo.PLUGIN_GUID);
            harmony.PatchAll();

            EnableAi = Config.Bind<bool>("AI", "Enable AI control", false);
            ShowGhostPath = Config.Bind<bool>("Visuals", "Show GTR Ghost Path", true);
            TelemetryPort = Config.Bind<int>("Network", "Telemetry Port", 9090);
            InputPort = Config.Bind<int>("Network", "Input Port", 9091);
            PointsTcpPort = Config.Bind<int>("Network", "Ghost Points TCP Port", 9092);

            gtrClient = new GtrClient.GtrClient(Logger);

            SetupNetwork();

            RacingApi.PlayerSpawned += () => {
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

                playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                string newHash = LevelApi.CurrentHash ?? LevelApi.CurrentLevel.UID;
                lastResetReason = "None";
                
                if (newHash != currentLevelHash || cachedPoints == null) {
                    Logger.LogInfo($"[AI_DEBUG] Level setup: Hash={newHash}, CacheReady={cachedPoints != null}. Fetching ghost.");
                    currentLevelHash = newHash;
                    ghostLoaded = false;
                    lock (ghostLock) { ghostReady = false; currentGhostBinary = null; }
                    cachedPoints = null;
                    cachedHash = "";
                    Task.Run(() => FetchAndProcessGhost(currentLevelHash));
                } else {
                    lock (ghostLock) { ghostReady = true; }
                }
            };

            RacingApi.Crashed += (reason) => { playerCar = null; lastResetReason = "Crashed: " + reason; };
            RacingApi.CrossedFinishLine += (time) => { playerCar = null; lastResetReason = "Finished"; };
            RacingApi.WheelBroken += () => { playerCar = null; lastResetReason = "Wheel Broken"; };
            RacingApi.PassedCheckpoint += (time) => { checkpointReached = true; };

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
                List<Vector3> points = await gtrClient.DownloadAndParseGhost(url);
                if (points == null) { Logger.LogError("[AI_DEBUG] Ghost parsing failed (returned null)."); return; }

                cachedPoints = points;
                cachedHash = hash;
                Logger.LogInfo($"[AI_DEBUG] Successfully processed {points.Count} points. Updating visualizer.");

                if (visualizer != null && ShowGhostPath.Value) {
                    UnityMainThreadDispatcher.Instance().Enqueue(() => { visualizer.UpdateLine(points); });
                }
                PrepareGhostBinary(points, hash);
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
                inputServer.BeginReceive(new AsyncCallback(OnReceiveInput), null);

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

        private void OnReceiveInput(IAsyncResult res)
        {
            try {
                byte[] bytes = inputServer.EndReceive(res, ref inputEndPoint);
                if (bytes.Length >= 8) {
                    lastInputTime = DateTime.Now;
                    using (MemoryStream ms = new MemoryStream(bytes))
                    using (BinaryReader reader = new BinaryReader(ms)) {
                        CurrentInput.Steering = reader.ReadSingle();
                        CurrentInput.Brake = reader.ReadBoolean();
                        CurrentInput.ArmsUp = reader.ReadBoolean();
                        CurrentInput.Reset = reader.ReadBoolean();
                        CurrentInput.RequestGhost = reader.ReadBoolean();
                        
                        inputPacketCount++;
                        if (inputPacketCount % 500 == 0) {
                            Logger.LogInfo($"[AI_DEBUG] Recv Input: Steer={CurrentInput.Steering:F2}, Brake={CurrentInput.Brake}");
                        }

                        if (bytes.Length > 8) {
                            string json = Encoding.UTF8.GetString(bytes, 8, bytes.Length - 8);
                            var data = JsonConvert.DeserializeObject<JsonInputData>(json);
                            if (data != null) {
                                lock (targetLock) { latestTargetPositions = data.p; }
                                CurrentInput.TrainingTime = data.t;
                            }
                        }
                    }
                    if (CurrentInput.RequestGhost && cachedPoints != null && cachedHash != "" && !isSendingPoints) {
                        SendPointsToPython(cachedPoints, cachedHash);
                    }
                }
            } catch { }
            try { inputServer.BeginReceive(new AsyncCallback(OnReceiveInput), null); } catch { }
        }

        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.F9)) {
                EnableAi.Value = !EnableAi.Value;
                Logger.LogInfo($"[AI_DEBUG] AI CONTROL: {(EnableAi.Value ? "ENABLED" : "DISABLED")}");
            }

            if (latestTargetPositions != null && targetVisualizer != null) {
                float[][] posToUpdate = null;
                lock (targetLock) { posToUpdate = latestTargetPositions; latestTargetPositions = null; }
                if (posToUpdate != null) targetVisualizer.UpdateTargets(posToUpdate);
            }
        }

        private void OnGUI()
        {
            if (EnableAi.Value && CurrentInput != null) {
                TimeSpan t = TimeSpan.FromSeconds(CurrentInput.TrainingTime);
                string timeStr = string.Format("{0:D2}:{1:D2}:{2:D2}", (int)t.TotalHours, t.Minutes, t.Seconds);
                GUIStyle style = new GUIStyle { fontSize = 72, fontStyle = FontStyle.Bold };
                style.normal.textColor = Color.black;
                GUI.Label(new Rect(22, 22, 1000, 100), $"Total Training Time: {timeStr}", style);
                style.normal.textColor = Color.white;
                GUI.Label(new Rect(20, 20, 1000, 100), $"Total Training Time: {timeStr}", style);
            }
        }

        private void FixedUpdate()
        {
            if (!EnableAi.Value) return;

            // Heartbeat: If Python pauses (training), hold last steering but don't reset.
            bool isPaused = (DateTime.Now - lastInputTime).TotalMilliseconds > 500;

            if (CurrentInput != null && CurrentInput.Reset && !isPaused) {
                if (PlayerManager.Instance?.currentMaster != null) {
                    PlayerManager.Instance.currentMaster.RestartLevel();
                    CurrentInput.Reset = false; playerCar = null;
                }
            }
            SendTelemetry();
        }

        private void SendTelemetry()
        {
            try {
                using (MemoryStream ms = new MemoryStream())
                using (BinaryWriter writer = new BinaryWriter(ms)) {
                    if (playerCar != null && playerCar.gameObject != null && playerCar.rb != null) {
                        var transform = playerCar.transform;
                        float[] rayDistances = new float[13];
                        for (int i = 0; i < 13; i++) {
                            float angle = -60f + (i * 10f);
                            Vector3 dir = Quaternion.Euler(0, angle, 0) * transform.forward;
                            float range = Mathf.Lerp(100f, 20f, Mathf.Abs(angle) / 60f);
                            rayDistances[i] = GetRaycast(dir, range, i);
                        }

                        bool isSlipping = false;
                        float friction = 1.0f;
                        if (playerCar.wheels != null) {
                            isSlipping = playerCar.wheels.Any(x => x != null && x.IsGrounded() && x.IsSlipping());
                            var grounded = playerCar.wheels.FirstOrDefault(x => x != null && x.IsGrounded());
                            if (grounded?.GetCurrentSurface()?.physics != null)
                                friction = grounded.GetCurrentSurface().physics.frictionFront;
                        }

                        writer.Write(Time.time);
                        writer.Write(transform.position.x); writer.Write(transform.position.y); writer.Write(transform.position.z);
                        writer.Write(transform.rotation.x); writer.Write(transform.rotation.y); writer.Write(transform.rotation.z); writer.Write(transform.rotation.w);
                        writer.Write(playerCar.rb.velocity.x); writer.Write(playerCar.rb.velocity.y); writer.Write(playerCar.rb.velocity.z);
                        writer.Write(playerCar.rb.angularVelocity.x); writer.Write(playerCar.rb.angularVelocity.y); writer.Write(playerCar.rb.angularVelocity.z);
                        writer.Write(playerCar.rb.velocity.magnitude);
                        writer.Write(true); writer.Write(ghostLoaded); writer.Write(ghostReady); writer.Write(checkpointReached);
                        foreach (float r in rayDistances) writer.Write(r);
                        writer.Write(isSlipping); writer.Write(friction);
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
                        for (int i = 0; i < 13; i++) writer.Write(0f);
                        writer.Write(false); writer.Write(1.0f);
                        writer.Write(currentLevelHash); writer.Write(lastResetReason);
                    }
                    byte[] bytes = ms.ToArray();
                    telemetryClient.Send(bytes, bytes.Length, telemetryEndPoint);
                }
            } catch { }
        }

        private float GetRaycast(Vector3 direction, float maxDist, int index = -1)
        {
            if (playerCar == null) return maxDist;
            Vector3 origin = playerCar.transform.position + Vector3.up * 0.5f;
            RaycastHit hit;
            float dist = maxDist;
            bool isObstacle = false;
            if (Physics.Raycast(origin, direction, out hit, maxDist)) {
                if (Mathf.Abs(hit.normal.y) < 0.8f) { dist = hit.distance; isObstacle = true; }
            }
            if (rayVisualizer != null && index >= 0) rayVisualizer.UpdateRay(index, origin, origin + direction * dist, isObstacle);
            return dist;
        }

        public void PrepareGhostBinary(List<Vector3> points, string levelHash)
        {
            List<float[]> downsampled = new List<float[]>();
            for (int i = 0; i < points.Count; i += 10)
                downsampled.Add(new float[] { points[i].x, points[i].y, points[i].z });

            var data = new { LevelHash = levelHash, FrameCount = downsampled.Count, Points = downsampled };
            byte[] bytes = Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(data));
            lock (ghostLock) { currentGhostBinary = bytes; ghostReady = true; }
        }

        public void OnDestroy() { harmony?.UnpatchSelf(); inputServer?.Close(); telemetryClient?.Close(); pointsTcpListener?.Stop(); }

        public void SendPointsToPython(List<Vector3> points, string levelHash) { PrepareGhostBinary(points, levelHash); }

        [HarmonyPatch(typeof(New_ControlCar), "Update")]
        public static class New_ControlCar_Update_Patch {
            public static void Postfix(New_ControlCar __instance) {
                if (EnableAi.Value && CurrentInput != null && playerCar != null && __instance == playerCar) {
                    if (__instance.SteerAction2 != null) __instance.SteerAction2.axis = CurrentInput.Steering;
                    if (__instance.BrakeAction2 != null) { __instance.BrakeAction2.axis = CurrentInput.Brake ? 1.0f : 0.0f; __instance.BrakeAction2.buttonHeld = CurrentInput.Brake; }
                    if (__instance.PitchBackwardAction2 != null) { __instance.PitchBackwardAction2.axis = CurrentInput.Brake ? 1.0f : 0.0f; __instance.PitchBackwardAction2.buttonHeld = CurrentInput.Brake; }
                    if (__instance.ArmsUpAction2 != null) { __instance.ArmsUpAction2.axis = CurrentInput.ArmsUp ? 1.0f : 0.0f; __instance.ArmsUpAction2.buttonHeld = CurrentInput.ArmsUp; }
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
        private void Awake() {
            lines = new LineRenderer[13];
            for (int i = 0; i < 13; i++) {
                GameObject obj = new GameObject($"Ray_{i}");
                obj.transform.SetParent(this.transform);
                lines[i] = obj.AddComponent<LineRenderer>();
                lines[i].useWorldSpace = true; lines[i].startWidth = 0.05f; lines[i].endWidth = 0.05f;
                lines[i].material = new Material(Shader.Find("Hidden/Internal-Colored"));
            }
        }
        public void UpdateRay(int idx, Vector3 start, Vector3 end, bool hit) {
            lines[idx].enabled = true; lines[idx].SetPositions(new Vector3[] { start, end });
            Color c = hit ? Color.red : Color.green;
            lines[idx].startColor = c; lines[idx].endColor = c;
        }
        private void Update() { if (Plugin.playerCar == null) foreach (var l in lines) l.enabled = false; }
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

    public class AiInput {
        public float Steering; public bool Brake; public bool ArmsUp; public bool Reset; public bool RequestGhost;
        public float[][] TargetPositions; public float TrainingTime;
    }
}

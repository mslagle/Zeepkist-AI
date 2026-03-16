using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using System;
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
using TNRD.Zeepkist.GTR.Ghosting.Readers;
using TNRD.Zeepkist.GTR.Ghosting.Ghosts;

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

        private static GtrClient.GtrClient gtrClient;
        private static List<Vector3> cachedPoints = null;
        private static string cachedHash = "";
        private static bool isSendingPoints = false;

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
                playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                string newHash = LevelApi.CurrentHash ?? LevelApi.CurrentLevel.UID;
                lastResetReason = "None";
                
                if (newHash != currentLevelHash)
                {
                    Debug.Log($"[AI_DEBUG] Level change detected: {currentLevelHash} -> {newHash}. Resetting state.");
                    currentLevelHash = newHash;
                    ghostLoaded = false;
                    cachedPoints = null;
                    cachedHash = "";
                    Task.Run(() => FetchAndProcessGhost(currentLevelHash));
                }
                
                if (visualizer == null)
                {
                    GameObject vizObj = new GameObject("AI_GhostVisualizer");
                    visualizer = vizObj.AddComponent<GhostVisualizer>();
                }

                if (rayVisualizer == null)
                {
                    GameObject rayObj = new GameObject("AI_RayVisualizer");
                    rayVisualizer = rayObj.AddComponent<RaycastVisualizer>();
                }

                if (targetVisualizer == null)
                {
                    GameObject targetObj = new GameObject("AI_TargetVisualizer");
                    targetVisualizer = targetObj.AddComponent<TargetVisualizer>();
                }
            };

            RacingApi.Crashed += (reason) => { 
                playerCar = null; 
                lastResetReason = "Crashed: " + reason;
            };
            RacingApi.CrossedFinishLine += (time) => { 
                playerCar = null; 
                lastResetReason = "Finished";
            };
            RacingApi.WheelBroken += () => { 
                playerCar = null; 
                lastResetReason = "Wheel Broken";
            };

            Logger.LogInfo($"[AI_DEBUG] Plugin fully initialized!");
        }

        private async Task FetchAndProcessGhost(string hash)
        {
            if (hash == "Unknown") return;

            try
            {
                Logger.LogInfo($"[AI_DEBUG] Fetching and parsing best ghost for {hash}...");
                string url = await gtrClient.GetBestGhostUrl(hash);
                if (string.IsNullOrEmpty(url))
                {
                    Logger.LogError($"[AI_DEBUG] No ghost found for {hash}");
                    return;
                }

                List<Vector3> points = await gtrClient.DownloadAndParseGhost(url);
                if (points == null) return;

                cachedPoints = points;
                cachedHash = hash;

                Logger.LogInfo($"[AI_DEBUG] Received {points.Count} points from GtrClient.");

                // Update visualizer on main thread
                if (visualizer != null && ShowGhostPath.Value)
                {
                    UnityMainThreadDispatcher.Instance().Enqueue(() => {
                        visualizer.UpdateLine(points);
                    });
                }

                SendPointsToPython(points, hash);
            }
            catch (Exception ex)
            {
                Logger.LogError($"[AI_DEBUG] Error in FetchAndProcessGhost: {ex.Message}");
            }
        }

        private void SetupNetwork()
        {
            try
            {
                telemetryClient = new UdpClient();
                telemetryEndPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), TelemetryPort.Value);

                inputServer = new UdpClient(InputPort.Value);
                inputEndPoint = new IPEndPoint(IPAddress.Any, InputPort.Value);
                inputServer.BeginReceive(new AsyncCallback(OnReceiveInput), null);

                pointsTcpListener = new TcpListener(IPAddress.Parse("127.0.0.1"), PointsTcpPort.Value);
                pointsTcpListener.Start();
                Logger.LogInfo($"[AI_DEBUG] TCP Points Server started on port {PointsTcpPort.Value}");
            }
            catch (Exception ex)
            {
                Logger.LogError($"AI Network Setup Error: {ex.Message}");
            }
        }

        private void OnReceiveInput(IAsyncResult res)
        {
            try
            {
                byte[] bytes = inputServer.EndReceive(res, ref inputEndPoint);
                string json = Encoding.UTF8.GetString(bytes);
                var input = JsonConvert.DeserializeObject<AiInput>(json);
                if (input != null)
                {
                    CurrentInput = input;
                    
                    if (CurrentInput.TargetPositions != null && targetVisualizer != null)
                    {
                        UnityMainThreadDispatcher.Instance().Enqueue(() => {
                            targetVisualizer.UpdateTargets(CurrentInput.TargetPositions);
                        });
                    }

                    if (CurrentInput.RequestGhost && cachedPoints != null && cachedHash != "" && !isSendingPoints)
                    {
                        SendPointsToPython(cachedPoints, cachedHash);
                    }
                }
            }
            catch { }

            try
            {
                inputServer.BeginReceive(new AsyncCallback(OnReceiveInput), null);
            }
            catch { }
        }

    public class TargetVisualizer : MonoBehaviour
    {
        private GameObject[] markers;
        private Color[] colors = new Color[] { Color.yellow, Color.cyan, Color.white, Color.white };

        private void Awake()
        {
            markers = new GameObject[4]; // 1 Nearest + 3 Lookaheads
            for (int i = 0; i < 4; i++)
            {
                markers[i] = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                markers[i].name = $"TargetMarker_{i}";
                markers[i].transform.SetParent(this.transform);
                markers[i].transform.localScale = Vector3.one * 1.5f;
                
                // Remove collider so it doesn't hit raycasts
                Destroy(markers[i].GetComponent<SphereCollider>());
                
                Renderer r = markers[i].GetComponent<Renderer>();
                r.material = new Material(Shader.Find("Hidden/Internal-Colored"));
                r.material.color = colors[i % colors.Length];
            }
        }

        public void UpdateTargets(float[][] positions)
        {
            if (positions == null) return;
            for (int i = 0; i < markers.Length; i++)
            {
                if (i < positions.Length)
                {
                    markers[i].SetActive(true);
                    markers[i].transform.position = new Vector3(positions[i][0], positions[i][1], positions[i][2]);
                }
                else
                {
                    markers[i].SetActive(false);
                }
            }
        }

        private void Update()
        {
            if (Plugin.playerCar == null)
            {
                foreach (var m in markers) if (m != null) m.SetActive(false);
            }
        }
    }

        private void FixedUpdate()
        {
            if (!EnableAi.Value) return;

            if (CurrentInput != null && CurrentInput.Reset)
            {
                if (PlayerManager.Instance != null && PlayerManager.Instance.currentMaster != null)
                {
                    PlayerManager.Instance.currentMaster.RestartLevel();
                    CurrentInput.Reset = false; 
                    playerCar = null;
                }
            }

            SendTelemetry();
        }

        private static bool ghostLoaded = false;
private float GetRaycast(Vector3 direction, float maxDist, int index = -1)
{
    if (playerCar == null) return maxDist;

    Vector3 origin = playerCar.transform.position + Vector3.up * 0.5f;
    RaycastHit hit;
    float dist = maxDist;
    bool isObstacle = false;

    if (Physics.Raycast(origin, direction, out hit, maxDist))
    {
        // Filter: Only count it as an obstacle if the surface is NOT flat ground.
        // A wall has a horizontal normal (low Y), ground has a vertical normal (high Y).
        if (Mathf.Abs(hit.normal.y) < 0.8f) 
        {
            dist = hit.distance;
            isObstacle = true;
        }
    }

    if (rayVisualizer != null && index >= 0)
    {
        rayVisualizer.UpdateRay(index, origin, origin + direction * dist, isObstacle);
    }

    return dist;
}


        private void SendTelemetry()
        {
            try
            {
                object data;
                if (playerCar != null && playerCar.gameObject != null && playerCar.rb != null)
                {
                    float maxRay = 40f;
                    var transform = playerCar.transform;
                    
                    float r0 = GetRaycast(transform.forward, maxRay, 0);
                    float r1 = GetRaycast(transform.forward + transform.right * 0.5f, maxRay, 1);
                    float r2 = GetRaycast(transform.forward - transform.right * 0.5f, maxRay, 2);
                    float r3 = GetRaycast(transform.right, 10f, 3);
                    float r4 = GetRaycast(-transform.right, 10f, 4);

                    data = new
                    {
                        Time = Time.time,
                        Position = new { x = transform.position.x, y = transform.position.y, z = transform.position.z },
                        Rotation = new { x = transform.rotation.x, y = transform.rotation.y, z = transform.rotation.z, w = transform.rotation.w },
                        Velocity = new { x = playerCar.rb.velocity.x, y = playerCar.rb.velocity.y, z = playerCar.rb.velocity.z },
                        AngularVelocity = new { x = playerCar.rb.angularVelocity.x, y = playerCar.rb.angularVelocity.y, z = playerCar.rb.angularVelocity.z },
                        Speed = playerCar.rb.velocity.magnitude,
                        LocalGForce = new { x = playerCar.localGForce.x, y = playerCar.localGForce.y },
                        LevelHash = currentLevelHash,
                        IsSpawned = true,
                        GhostLoaded = ghostLoaded,
                        ResetReason = lastResetReason,
                        Rays = new float[] { r0, r1, r2, r3, r4 }
                    };
                }
                else
                {
                    data = new { Time = Time.time, IsSpawned = false, LevelHash = currentLevelHash, GhostLoaded = ghostLoaded, ResetReason = lastResetReason };
                }

                string json = JsonConvert.SerializeObject(data);
                byte[] bytes = Encoding.UTF8.GetBytes(json);
                telemetryClient.Send(bytes, bytes.Length, telemetryEndPoint);
            }
            catch { }
        }

        public void OnDestroy()
        {
            harmony?.UnpatchSelf();
            inputServer?.Close();
            telemetryClient?.Close();
            pointsTcpListener?.Stop();
            if (visualizer != null) Destroy(visualizer.gameObject);
        }

        public void SendPointsToPython(List<Vector3> points, string levelHash)
        {
            if (points == null || points.Count == 0 || isSendingPoints) return;

            isSendingPoints = true;
            Task.Run(() => {
                try {
                    // Downsample: Take every 10th point
                    List<float[]> downsampled = new List<float[]>();
                    for (int i = 0; i < points.Count; i += 10) {
                        downsampled.Add(new float[] { points[i].x, points[i].y, points[i].z });
                    }

                    Logger.LogInfo($"[AI_DEBUG] Waiting for Python TCP connection to send {downsampled.Count} points...");
                    
                    using (TcpClient client = pointsTcpListener.AcceptTcpClient())
                    using (NetworkStream stream = client.GetStream())
                    {
                        var data = new { 
                            LevelHash = levelHash, 
                            FrameCount = downsampled.Count, 
                            Points = downsampled 
                        };
                        string json = JsonConvert.SerializeObject(data);
                        byte[] bytes = Encoding.UTF8.GetBytes(json);
                        
                        // Send size first (4 bytes)
                        byte[] sizeBytes = BitConverter.GetBytes(bytes.Length);
                        stream.Write(sizeBytes, 0, 4);
                        
                        // Send data
                        stream.Write(bytes, 0, bytes.Length);
                        Logger.LogInfo($"[AI_DEBUG] Successfully sent all points over TCP.");
                        ghostLoaded = true;
                    }
                } catch (Exception ex) {
                    Logger.LogError($"[AI_DEBUG] TCP Send Error: {ex.Message}");
                } finally {
                    isSendingPoints = false;
                }
            });
        }

        [HarmonyPatch(typeof(New_ControlCar), "Update")]
        public static class New_ControlCar_Update_Patch
        {
            public static void Postfix(New_ControlCar __instance)
            {
                if (EnableAi.Value && CurrentInput != null && playerCar != null && __instance == playerCar)
                {
                    if (__instance.SteerAction2 != null) __instance.SteerAction2.axis = CurrentInput.Steering;
                    if (__instance.BrakeAction2 != null)
                    {
                        __instance.BrakeAction2.axis = CurrentInput.Brake ? 1.0f : 0.0f;
                        __instance.BrakeAction2.buttonHeld = CurrentInput.Brake;
                    }
                    if (__instance.PitchBackwardAction2 != null)
                    {
                        __instance.PitchBackwardAction2.axis = CurrentInput.Brake ? 1.0f : 0.0f;
                        __instance.PitchBackwardAction2.buttonHeld = CurrentInput.Brake;
                    }
                    if (__instance.ArmsUpAction2 != null)
                    {
                        __instance.ArmsUpAction2.axis = CurrentInput.ArmsUp ? 1.0f : 0.0f;
                        __instance.ArmsUpAction2.buttonHeld = CurrentInput.ArmsUp;
                    }
                }
            }
        }
    }

    public class UnityMainThreadDispatcher : MonoBehaviour
    {
        private static readonly Queue<Action> _executionQueue = new Queue<Action>();
        private static UnityMainThreadDispatcher _instance = null;

        public static UnityMainThreadDispatcher Instance()
        {
            if (_instance == null)
            {
                GameObject obj = new GameObject("UnityMainThreadDispatcher");
                _instance = obj.AddComponent<UnityMainThreadDispatcher>();
                DontDestroyOnLoad(obj);
            }
            return _instance;
        }

        public void Update()
        {
            lock (_executionQueue)
            {
                while (_executionQueue.Count > 0)
                {
                    _executionQueue.Dequeue().Invoke();
                }
            }
        }

        public void Enqueue(Action action)
        {
            lock (_executionQueue)
            {
                _executionQueue.Enqueue(action);
            }
        }
    }

    public class GhostVisualizer : MonoBehaviour
    {
        private LineRenderer line;

        private void Awake()
        {
            line = gameObject.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.startWidth = 1.0f;
            line.endWidth = 1.0f;
            line.positionCount = 0;
            line.material = new Material(Shader.Find("Sprites/Default"));
            line.startColor = Color.magenta;
            line.endColor = Color.magenta;
            line.sortingOrder = 10000;
        }

        public void UpdateLine(List<Vector3> points)
        {
            if (points == null) return;
            line.positionCount = points.Count;
            line.SetPositions(points.ToArray());
        }
    }

    public class RaycastVisualizer : MonoBehaviour
    {
        private LineRenderer[] lines;
        private const int RayCount = 5;

        private void Awake()
        {
            lines = new LineRenderer[RayCount];
            for (int i = 0; i < RayCount; i++)
            {
                GameObject lineObj = new GameObject($"RayLine_{i}");
                lineObj.transform.SetParent(this.transform);
                LineRenderer lr = lineObj.AddComponent<LineRenderer>();
                lr.useWorldSpace = true;
                lr.startWidth = 0.1f;
                lr.endWidth = 0.1f;
                lr.material = new Material(Shader.Find("Hidden/Internal-Colored"));
                lr.material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
                lr.material.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
                lr.material.SetInt("_Cull", (int)UnityEngine.Rendering.CullMode.Off);
                lr.material.SetInt("_ZWrite", 0);
                lines[i] = lr;
            }
        }

        public void UpdateRay(int index, Vector3 start, Vector3 end, bool hasHit)
        {
            if (index < 0 || index >= RayCount) return;
            
            lines[index].enabled = true;
            lines[index].SetPosition(0, start);
            lines[index].SetPosition(1, end);
            
            Color color = hasHit ? Color.red : Color.green;
            lines[index].startColor = color;
            lines[index].endColor = color;
        }

        private void Update()
        {
            if (Plugin.playerCar == null)
            {
                foreach (var line in lines) if (line != null) line.enabled = false;
            }
        }
    }

    [Serializable]
    public class AiInput
    {
        public float Steering;
        public bool Brake;
        public bool ArmsUp;
        public bool Reset;
        public bool RequestGhost;
        public float[][] TargetPositions;
    }
}

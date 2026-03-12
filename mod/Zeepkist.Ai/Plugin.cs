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
        public static ConfigEntry<int> PointsPort { get; private set; }

        private static UdpClient telemetryClient;
        private static IPEndPoint telemetryEndPoint;
        private static UdpClient inputServer;
        private static IPEndPoint inputEndPoint;
        private static UdpClient pointsClient;
        private static IPEndPoint pointsEndPoint;

        public static AiInput CurrentInput { get; private set; } = new AiInput();
        private static New_ControlCar playerCar = null;
        private static string currentLevelHash = "Unknown";
        private static GhostVisualizer visualizer = null;

        private static GtrClient.GtrClient gtrClient;
        private static List<Vector3> cachedPoints = null;
        private static string cachedHash = "";

        private void Awake()
        {
            Debug.Log("[AI_DEBUG] === Plugin.Awake() STARTING ===");
            harmony = new Harmony(MyPluginInfo.PLUGIN_GUID);
            harmony.PatchAll();

            EnableAi = Config.Bind<bool>("AI", "Enable AI control", false);
            ShowGhostPath = Config.Bind<bool>("Visuals", "Show GTR Ghost Path", true);
            TelemetryPort = Config.Bind<int>("Network", "Telemetry Port", 9090);
            InputPort = Config.Bind<int>("Network", "Input Port", 9091);
            PointsPort = Config.Bind<int>("Network", "Ghost Points Port", 9092);

            gtrClient = new GtrClient.GtrClient();

            SetupNetwork();

            RacingApi.PlayerSpawned += () => {
                playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                string newHash = LevelApi.CurrentLevel?.UID ?? "Unknown";
                
                if (newHash != currentLevelHash)
                {
                    currentLevelHash = newHash;
                    ghostLoaded = false;
                    Task.Run(() => FetchAndProcessGhost(currentLevelHash));
                }
                
                if (visualizer == null)
                {
                    GameObject vizObj = new GameObject("AI_GhostVisualizer");
                    visualizer = vizObj.AddComponent<GhostVisualizer>();
                }
            };

            RacingApi.Crashed += (reason) => { playerCar = null; };
            RacingApi.CrossedFinishLine += (time) => { playerCar = null; };
            RacingApi.WheelBroken += () => { playerCar = null; };

            Debug.Log($"[AI_DEBUG] Plugin fully initialized!");
        }

        private async Task FetchAndProcessGhost(string hash)
        {
            if (hash == "Unknown") return;

            try
            {
                Debug.Log($"[AI_DEBUG] Fetching and parsing best ghost for {hash}...");
                string url = await gtrClient.GetBestGhostUrl(hash);
                if (string.IsNullOrEmpty(url))
                {
                    Debug.LogWarning($"[AI_DEBUG] No ghost found for {hash}");
                    return;
                }

                List<Vector3> points = await gtrClient.DownloadAndParseGhost(url);
                if (points == null) return;

                cachedPoints = points;
                cachedHash = hash;

                Debug.Log($"[AI_DEBUG] Received {points.Count} points from GtrClient.");

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
                Debug.LogError($"[AI_DEBUG] Error in FetchAndProcessGhost: {ex.Message}");
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

                pointsClient = new UdpClient();
                pointsEndPoint = new IPEndPoint(IPAddress.Parse("127.0.0.1"), PointsPort.Value);
            }
            catch (Exception ex)
            {
                Debug.LogError($"AI Network Setup Error: {ex.Message}");
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
                    if (CurrentInput.RequestGhost && cachedPoints != null && cachedHash != "")
                    {
                        // We use a separate thread so we don't block input processing
                        Task.Run(() => SendPointsToPython(cachedPoints, cachedHash));
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

        private void SendTelemetry()
        {
            try
            {
                object data;
                if (playerCar != null && playerCar.gameObject != null && playerCar.rb != null)
                {
                    data = new
                    {
                        Time = Time.time,
                        Position = new { x = playerCar.transform.position.x, y = playerCar.transform.position.y, z = playerCar.transform.position.z },
                        Rotation = new { x = playerCar.transform.rotation.x, y = playerCar.transform.rotation.y, z = playerCar.transform.rotation.z, w = playerCar.transform.rotation.w },
                        Velocity = new { x = playerCar.rb.velocity.x, y = playerCar.rb.velocity.y, z = playerCar.rb.velocity.z },
                        AngularVelocity = new { x = playerCar.rb.angularVelocity.x, y = playerCar.rb.angularVelocity.y, z = playerCar.rb.angularVelocity.z },
                        Speed = playerCar.rb.velocity.magnitude,
                        LocalGForce = new { x = playerCar.localGForce.x, y = playerCar.localGForce.y },
                        LevelHash = currentLevelHash,
                        IsSpawned = true,
                        GhostLoaded = ghostLoaded
                    };
                }
                else
                {
                    data = new { Time = Time.time, IsSpawned = false, LevelHash = currentLevelHash, GhostLoaded = ghostLoaded };
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
            pointsClient?.Close();
            if (visualizer != null) Destroy(visualizer.gameObject);
        }

        public static void SendPointsToPython(List<Vector3> points, string levelHash)
        {
            if (points == null || points.Count == 0)
            {
                Debug.LogWarning("[AI_DEBUG] No points to send to Python.");
                return;
            }

            try {
                Debug.Log($"[AI_DEBUG] Sending metadata for {points.Count} points...");
                var metadata = new { Type = "Metadata", LevelHash = levelHash, FrameCount = points.Count };
                byte[] metaBytes = Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(metadata));
                pointsClient.Send(metaBytes, metaBytes.Length, pointsEndPoint);

                System.Threading.Thread.Sleep(50); // Give Python time to prepare

                int chunkSize = 50; // Smaller chunks to stay under MTU
                for (int i = 0; i < points.Count; i += chunkSize) {
                    var chunk = points.Skip(i).Take(chunkSize).Select(p => new { p = new float[] { p.x, p.y, p.z } }).ToList();
                    var data = new { Type = "Points", Points = chunk, IsLast = (i + chunkSize >= points.Count) };
                    byte[] bytes = Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(data));
                    pointsClient.Send(bytes, bytes.Length, pointsEndPoint);
                    System.Threading.Thread.Sleep(10); 
                }
                Debug.Log($"[AI_DEBUG] Successfully sent {points.Count} points to Python.");
                ghostLoaded = true;
            } catch (Exception ex) {
                Debug.LogError($"[AI_DEBUG] Error sending points: {ex.Message}");
            }
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

    [Serializable]
    public class AiInput
    {
        public float Steering;
        public bool Brake;
        public bool ArmsUp;
        public bool Reset;
        public bool RequestGhost;
    }
}

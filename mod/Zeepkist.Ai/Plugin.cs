using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using UnityEngine;
using ZeepSDK.Racing;
using ZeepSDK.Level;
using Newtonsoft.Json;
using System.Net.Http;
using System.Threading.Tasks;
using System.IO;

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

        public static AiInput CurrentInput { get; private set; } = new AiInput();
        private static New_ControlCar playerCar = null;
        private static string currentLevelHash = "Unknown";
        private static string currentGhostUrl = "";
        private static GhostVisualizer visualizer = null;

        private void Awake()
        {
            Debug.Log("[AI_DEBUG] === Plugin.Awake() STARTING ===");
            Harmony.DEBUG = true;
            harmony = new Harmony(MyPluginInfo.PLUGIN_GUID);
            harmony.PatchAll();
            Debug.Log("[AI_DEBUG] === Harmony patches applied ===");

            EnableAi = Config.Bind<bool>("AI", "Enable AI control", false);
            ShowGhostPath = Config.Bind<bool>("Visuals", "Show GTR Ghost Path", true);
            TelemetryPort = Config.Bind<int>("Network", "Telemetry Port", 9090);
            InputPort = Config.Bind<int>("Network", "Input Port", 9091);
            PointsPort = Config.Bind<int>("Network", "Ghost Points Port", 9092);

            SetupNetwork();

            RacingApi.PlayerSpawned += () => {
                Debug.Log("[AI_DEBUG] RacingApi.PlayerSpawned Event Triggered");
                playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                currentLevelHash = LevelApi.CurrentLevel?.UID ?? "Unknown";
                Debug.Log($"[AI_DEBUG] Level Hash: {currentLevelHash}");
                
                if (visualizer == null)
                {
                    Debug.Log("[AI_DEBUG] Creating GhostVisualizer GameObject");
                    GameObject vizObj = new GameObject("AI_GhostVisualizer");
                    visualizer = vizObj.AddComponent<GhostVisualizer>();
                    visualizer.Initialize(PointsPort.Value);
                }
                visualizer.RefreshGhost(currentLevelHash);
            };

            RacingApi.Crashed += (reason) => { playerCar = null; Debug.Log("[AI_DEBUG] RacingApi.Crashed"); };
            RacingApi.CrossedFinishLine += (time) => { playerCar = null; Debug.Log("[AI_DEBUG] RacingApi.CrossedFinishLine"); };
            RacingApi.WheelBroken += () => { playerCar = null; Debug.Log("[AI_DEBUG] RacingApi.WheelBroken"); };

            Debug.Log($"[AI_DEBUG] Plugin {MyPluginInfo.PLUGIN_GUID} fully initialized!");
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
                CurrentInput = JsonConvert.DeserializeObject<AiInput>(json);
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
                        GhostUrl = currentGhostUrl,
                        IsSpawned = true
                    };
                }
                else
                {
                    data = new { Time = Time.time, IsSpawned = false, LevelHash = currentLevelHash, GhostUrl = currentGhostUrl };
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
            if (visualizer != null) Destroy(visualizer.gameObject);
        }

        public static void SetGhostUrl(string url)
        {
            currentGhostUrl = url;
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

    public class GhostVisualizer : MonoBehaviour
    {
        private LineRenderer line;
        private string lastHash = "";
        private static readonly HttpClient client = new HttpClient();
        private UdpClient pointsServer;
        private IPEndPoint pointsEndPoint;
        private List<Vector3> receivedPoints = new List<Vector3>();
        private bool hasNewPoints = false;

        public void Initialize(int port)
        {
            Debug.Log($"[AI_DEBUG] Initializing Points Receiver on port {port}");
            try {
                if (pointsServer != null) pointsServer.Close();
                pointsServer = new UdpClient(port);
                pointsEndPoint = new IPEndPoint(IPAddress.Any, port);
                pointsServer.BeginReceive(new AsyncCallback(OnReceivePoints), null);
                Debug.Log($"[AI_DEBUG] UDP Points Receiver successfully started on port {port}");
            } catch (Exception ex) {
                Debug.LogError($"[AI_DEBUG] CRITICAL: Failed to start points receiver: {ex.Message}");
            }
        }

        private void OnReceivePoints(IAsyncResult res)
        {
            try {
                byte[] bytes = pointsServer.EndReceive(res, ref pointsEndPoint);
                string json = Encoding.UTF8.GetString(bytes);
                Debug.Log($"[AI_DEBUG] Received UDP packet: {bytes.Length} bytes.");
                
                var wrapper = JsonConvert.DeserializeObject<PointsWrapper>(json);
                if (wrapper != null && wrapper.Points != null) {
                    lock(receivedPoints) {
                        int startCount = receivedPoints.Count;
                        foreach (var p in wrapper.Points) {
                            receivedPoints.Add(new Vector3(p[0], p[1] + 2.0f, p[2]));
                        }
                        hasNewPoints = true;
                        Debug.Log($"[AI_DEBUG] Parsed {wrapper.Points.Count} points. Total in queue: {receivedPoints.Count}");
                        if (wrapper.Points.Count > 0) {
                            var first = wrapper.Points[0];
                            Debug.Log($"[AI_DEBUG] Sample point (raw): {first[0]}, {first[1]}, {first[2]}");
                        }
                    }
                } else {
                    Debug.LogWarning("[AI_DEBUG] Received packet but Points wrapper was null or empty.");
                }
            } catch (Exception ex) {
                Debug.LogError($"[AI_DEBUG] Error in OnReceivePoints: {ex.Message}\n{ex.StackTrace}");
            }

            try {
                pointsServer.BeginReceive(new AsyncCallback(OnReceivePoints), null);
            } catch (Exception ex) {
                Debug.LogError($"[AI_DEBUG] Error restarting BeginReceive: {ex.Message}");
            }
        }

        private void Awake()
        {
            Debug.Log("[AI_DEBUG] GhostVisualizer component is waking up...");
            line = gameObject.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.startWidth = 2.0f;
            line.endWidth = 2.0f;
            line.positionCount = 0;
            
            Shader shader = Shader.Find("Hidden/Internal-CombinedDiffuse");
            if (shader == null) shader = Shader.Find("Sprites/Default");
            Debug.Log($"[AI_DEBUG] Using shader: {shader?.name ?? "NULL"}");
            
            line.material = new Material(shader);
            line.startColor = Color.magenta;
            line.endColor = Color.magenta;
            line.sortingOrder = 10000;
            
            Debug.Log("[AI_DEBUG] GhostVisualizer LineRenderer configured.");
        }

        private void Update()
        {
            if (hasNewPoints) {
                lock(receivedPoints) {
                    Debug.Log($"[AI_DEBUG] Update loop: Applying {receivedPoints.Count} points to LineRenderer.");
                    line.positionCount = receivedPoints.Count;
                    line.SetPositions(receivedPoints.ToArray());
                    hasNewPoints = false;
                    Debug.Log("[AI_DEBUG] Update loop: LineRenderer positions updated.");
                }
            }
        }

        public async void RefreshGhost(string levelHash)
        {
            Debug.Log($"[AI_DEBUG] RefreshGhost called for level: {levelHash}");
            if (levelHash == lastHash || levelHash == "Unknown") {
                Debug.Log($"[AI_DEBUG] Skipping refresh (Last: {lastHash}, New: {levelHash})");
                return;
            }
            lastHash = levelHash;
            
            lock(receivedPoints) {
                line.positionCount = 0;
                receivedPoints.Clear();
                Debug.Log("[AI_DEBUG] Cleared old ghost points.");
            }
            
            Plugin.SetGhostUrl("");

            try
            {
                Debug.Log("[AI_DEBUG] Fetching ghost URL via GraphQL...");
                string ghostUrl = await FetchGhostUrl(levelHash);
                if (!string.IsNullOrEmpty(ghostUrl)) {
                    Debug.Log($"[AI_DEBUG] Found ghost URL: {ghostUrl}");
                    Plugin.SetGhostUrl(ghostUrl);
                } else {
                    Debug.LogWarning("[AI_DEBUG] GraphQL returned no ghost URL for this level.");
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[AI_DEBUG] RefreshGhost Exception: {ex.Message}");
            }
        }

        private async Task<string> FetchGhostUrl(string hash)
        {
            string query = "{\"query\": \"query GetGhost($hash: String!) { levels(filter: { hash: { equalTo: $hash } }) { nodes { records(orderBy: TIME_ASC, first: 10) { nodes { recordMedia { ghostUrl } } } } } }\", \"variables\": { \"hash\": \"" + hash + "\" }}";
            var content = new StringContent(query, Encoding.UTF8, "application/json");
            var response = await client.PostAsync("https://graphql.zeepki.st", content);
            var json = await response.Content.ReadAsStringAsync();
            
            List<string> urls = new List<string>();
            int currentPos = 0;
            while (true)
            {
                int urlIndex = json.IndexOf("\"ghostUrl\":\"", currentPos);
                if (urlIndex == -1) break;
                int start = urlIndex + 12;
                int end = json.IndexOf("\"", start);
                string url = json.Substring(start, end - start);
                if (url.StartsWith("//")) url = "https:" + url;
                urls.Add(url);
                currentPos = end;
            }

            if (urls.Count == 0) return null;
            int indexToPick = urls.Count >= 5 ? 4 : 0; // Prefer 5th rank for natural line
            return urls[indexToPick];
        }

        private class PointsWrapper {
            public List<float[]> Points { get; set; }
        }

        private void OnDestroy() {
            pointsServer?.Close();
        }
    }

    [Serializable]
    public class AiInput
    {
        public float Steering;
        public bool Brake;
        public bool ArmsUp;
        public bool Reset;
    }
}

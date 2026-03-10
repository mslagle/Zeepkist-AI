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
            harmony = new Harmony(MyPluginInfo.PLUGIN_GUID);
            harmony.PatchAll();

            EnableAi = Config.Bind<bool>("AI", "Enable AI control", false);
            ShowGhostPath = Config.Bind<bool>("Visuals", "Show GTR Ghost Path", true);
            TelemetryPort = Config.Bind<int>("Network", "Telemetry Port", 9090);
            InputPort = Config.Bind<int>("Network", "Input Port", 9091);
            PointsPort = Config.Bind<int>("Network", "Ghost Points Port", 9092);

            SetupNetwork();

            RacingApi.PlayerSpawned += () => {
                playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                currentLevelHash = LevelApi.CurrentLevel?.UID ?? "Unknown";
                
                if (visualizer == null)
                {
                    GameObject vizObj = new GameObject("AI_GhostVisualizer");
                    visualizer = vizObj.AddComponent<GhostVisualizer>();
                    visualizer.Initialize(PointsPort.Value);
                }
                visualizer.RefreshGhost(currentLevelHash);
            };

            RacingApi.Crashed += (reason) => playerCar = null;
            RacingApi.CrossedFinishLine += (time) => playerCar = null;
            RacingApi.WheelBroken += () => playerCar = null;

            Debug.Log($"Plugin {MyPluginInfo.PLUGIN_GUID} is loaded!");
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
            try {
                if (pointsServer != null) pointsServer.Close();
                pointsServer = new UdpClient(port);
                pointsEndPoint = new IPEndPoint(IPAddress.Any, port);
                pointsServer.BeginReceive(new AsyncCallback(OnReceivePoints), null);
                Debug.Log($"AI: Ghost Points receiver started on port {port}");
            } catch (Exception ex) {
                Debug.LogError($"AI: Failed to start points receiver: {ex.Message}");
            }
        }

        private void OnReceivePoints(IAsyncResult res)
        {
            try {
                byte[] bytes = pointsServer.EndReceive(res, ref pointsEndPoint);
                string json = Encoding.UTF8.GetString(bytes);
                // Debug.Log($"AI: Received UDP packet ({bytes.Length} bytes)");
                
                var wrapper = JsonConvert.DeserializeObject<PointsWrapper>(json);
                if (wrapper != null && wrapper.Points != null) {
                    lock(receivedPoints) {
                        receivedPoints.AddRange(wrapper.Points.Select(p => new Vector3(p[0], p[1], p[2])));
                        hasNewPoints = true;
                    }
                    // Debug.Log($"AI: Parsed {wrapper.Points.Count} points. Total queue: {receivedPoints.Count}");
                }
            } catch (Exception ex) {
                Debug.LogError($"AI: Error receiving/parsing points: {ex.Message}");
            }

            try {
                pointsServer.BeginReceive(new AsyncCallback(OnReceivePoints), null);
            } catch { }
        }

        private void Awake()
        {
            line = gameObject.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.startWidth = 1.0f; // Thicker for visibility
            line.endWidth = 1.0f;
            line.positionCount = 0;
            
            // Try different shaders if one fails
            line.material = new Material(Shader.Find("Unlit/Color"));
            if (line.material == null) line.material = new Material(Shader.Find("Sprites/Default"));
            
            line.startColor = Color.green; // Bright green for visibility
            line.endColor = Color.green;
            line.sortingOrder = 9999;
            
            Debug.Log("AI: GhostVisualizer created and initialized.");
        }

        private void Update()
        {
            if (hasNewPoints) {
                lock(receivedPoints) {
                    Debug.Log($"AI: Updating LineRenderer with {receivedPoints.Count} points.");
                    line.positionCount = receivedPoints.Count;
                    line.SetPositions(receivedPoints.ToArray());
                    hasNewPoints = false;
                }
            }
        }

        public async void RefreshGhost(string levelHash)
        {
            if (levelHash == lastHash || levelHash == "Unknown") return;
            Debug.Log($"AI: Refreshing ghost for level {levelHash}");
            lastHash = levelHash;
            
            lock(receivedPoints) {
                line.positionCount = 0;
                receivedPoints.Clear();
            }
            
            Plugin.SetGhostUrl("");

            try
            {
                string ghostUrl = await FetchGhostUrl(levelHash);
                if (!string.IsNullOrEmpty(ghostUrl)) {
                    Plugin.SetGhostUrl(ghostUrl);
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"Ghost Visualizer Error: {ex.Message}");
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

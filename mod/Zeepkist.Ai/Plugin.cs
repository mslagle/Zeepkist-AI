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

            SetupNetwork();

            RacingApi.PlayerSpawned += () => {
                playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                currentLevelHash = LevelApi.CurrentLevel?.UID ?? "Unknown";
                Debug.Log($"AI: Player spawned on level {currentLevelHash}");

                if (visualizer == null)
                {
                    GameObject vizObj = new GameObject("AI_GhostVisualizer");
                    visualizer = vizObj.AddComponent<GhostVisualizer>();
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

        private void Awake()
        {
            line = gameObject.AddComponent<LineRenderer>();
            line.startWidth = 0.5f;
            line.endWidth = 0.5f;
            line.positionCount = 0;
            line.material = new Material(Shader.Find("Sprites/Default"));
            line.startColor = Color.cyan;
            line.endColor = Color.blue;
        }

        public async void RefreshGhost(string levelHash)
        {
            if (levelHash == lastHash || levelHash == "Unknown") return;
            lastHash = levelHash;
            line.positionCount = 0;
            Plugin.SetGhostUrl("");

            try
            {
                string ghostUrl = await FetchGhostUrl(levelHash);
                if (string.IsNullOrEmpty(ghostUrl)) return;

                Plugin.SetGhostUrl(ghostUrl);

                if (Plugin.ShowGhostPath.Value)
                {
                    byte[] data = await client.GetByteArrayAsync(ghostUrl);
                    List<Vector3> points = ParseGhostPoints(data);
                    if (points.Count > 0)
                    {
                        line.positionCount = points.Count;
                        line.SetPositions(points.ToArray());
                    }
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"Ghost Visualizer Error: {ex.Message}");
            }
        }

        private async Task<string> FetchGhostUrl(string hash)
        {
            // Fetch top 10 records instead of just 1
            string query = "{\"query\": \"query GetGhost($hash: String!) { levels(filter: { hash: { equalTo: $hash } }) { nodes { records(orderBy: TIME_ASC, first: 10) { nodes { recordMedia { ghostUrl } } } } } }\", \"variables\": { \"hash\": \"" + hash + "\" }}";
            var content = new StringContent(query, Encoding.UTF8, "application/json");
            var response = await client.PostAsync("https://graphql.zeepki.st", content);
            var json = await response.Content.ReadAsStringAsync();
            
            // Collect all ghostUrls found
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

            // Pick a "middle-ranked" ghost if possible (e.g. 5th to 10th)
            // Fastest ghosts often use exploits or "weird tricks" that are bad for general AI training.
            int indexToPick = 0; // Default to fastest if only 1
            if (urls.Count >= 10) indexToPick = UnityEngine.Random.Range(4, 10); // 5th to 10th
            else if (urls.Count >= 5) indexToPick = UnityEngine.Random.Range(2, urls.Count); // 3rd to last
            else if (urls.Count > 1) indexToPick = urls.Count - 1; // Last one available

            Debug.Log($"AI: Picking ghost rank {indexToPick + 1} of {urls.Count} for more 'natural' racing line.");
            return urls[indexToPick];
        }

        private List<Vector3> ParseGhostPoints(byte[] data)
        {
            List<Vector3> points = new List<Vector3>();
            if (data[0] == 0x5D) 
            {
                // LZMA visualization skipped for now
                return points;
            }

            using (MemoryStream ms = new MemoryStream(data))
            using (BinaryReader reader = new BinaryReader(ms))
            {
                try {
                    while (ms.Position + 28 <= ms.Length) {
                        float x = reader.ReadSingle();
                        float y = reader.ReadSingle();
                        float z = reader.ReadSingle();
                        points.Add(new Vector3(x, y, z));
                        ms.Seek(16, SeekOrigin.Current); 
                    }
                } catch { }
            }
            return points;
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

public static class StringExtensions
{
    public static int indexOf(this string str, string value, int startIndex = 0)
    {
        return str.IndexOf(value, startIndex);
    }
}

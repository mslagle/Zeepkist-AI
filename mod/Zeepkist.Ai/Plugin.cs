using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using System;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using UnityEngine;
using ZeepSDK.Racing;
using ZeepSDK.Level;
using Newtonsoft.Json;

namespace Zeepkist.Ai
{
    [BepInPlugin(MyPluginInfo.PLUGIN_GUID, MyPluginInfo.PLUGIN_NAME, MyPluginInfo.PLUGIN_VERSION)]
    [BepInDependency("ZeepSDK")]
    public class Plugin : BaseUnityPlugin
    {
        private Harmony harmony;

        public static ConfigEntry<bool> EnableAi { get; private set; }
        public static ConfigEntry<int> TelemetryPort { get; private set; }
        public static ConfigEntry<int> InputPort { get; private set; }

        private static UdpClient telemetryClient;
        private static IPEndPoint telemetryEndPoint;
        private static UdpClient inputServer;
        private static IPEndPoint inputEndPoint;

        public static AiInput CurrentInput { get; private set; } = new AiInput();
        private static New_ControlCar playerCar = null;
        private static string currentLevelHash = "Unknown";

        private void Awake()
        {
            harmony = new Harmony(MyPluginInfo.PLUGIN_GUID);
            harmony.PatchAll();

            EnableAi = Config.Bind<bool>("AI", "Enable AI control", false);
            TelemetryPort = Config.Bind<int>("Network", "Telemetry Port", 9090);
            InputPort = Config.Bind<int>("Network", "Input Port", 9091);

            SetupNetwork();

            RacingApi.PlayerSpawned += () => {
                playerCar = PlayerManager.Instance.currentMaster.carSetups.First().cc;
                currentLevelHash = LevelApi.CurrentLevel?.UID ?? "Unknown";
                Debug.Log($"AI: Player spawned on level {currentLevelHash}");
            };

            RacingApi.Crashed += (reason) => playerCar = null;
            RacingApi.CrossedFinishLine += (time) => playerCar = null;

            Debug.Log($"Plugin {MyPluginInfo.PLUGIN_GUID} is loaded and networking is setup!");
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

            // Handle Reset globally
            if (CurrentInput != null && CurrentInput.Reset)
            {
                if (PlayerManager.Instance != null && PlayerManager.Instance.currentMaster != null)
                {
                    Debug.Log("AI: Reset requested, restarting level.");
                    PlayerManager.Instance.currentMaster.RestartLevel();
                    CurrentInput.Reset = false; 
                    playerCar = null; // Clear immediately so IsSpawned becomes false
                }
            }

            SendTelemetry();
        }

        private void SendTelemetry()
        {
            try
            {
                object data;
                // Double check if car is still valid/active
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
                        IsSpawned = true
                    };
                }
                else
                {
                    data = new { Time = Time.time, IsSpawned = false, LevelHash = currentLevelHash };
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
        }

        [HarmonyPatch(typeof(New_ControlCar), "Update")]
        public static class New_ControlCar_Update_Patch
        {
            public static void Postfix(New_ControlCar __instance)
            {
                if (EnableAi.Value && CurrentInput != null)
                {
                    if (playerCar != null && __instance == playerCar)
                    {
                        if (__instance.SteerAction2 != null)
                            __instance.SteerAction2.axis = CurrentInput.Steering;
                        
                        if (__instance.PitchForwardAction2 != null)
                        {
                            float accel = Mathf.Max(0, CurrentInput.Acceleration);
                            __instance.PitchForwardAction2.axis = accel;
                            __instance.PitchForwardAction2.buttonHeld = accel > 0.1f;
                        }

                        if (__instance.BrakeAction2 != null)
                        {
                            __instance.BrakeAction2.axis = CurrentInput.Brake ? 1.0f : 0.0f;
                            __instance.BrakeAction2.buttonHeld = CurrentInput.Brake;
                        }

                        if (__instance.PitchBackwardAction2 != null)
                        {
                            float reverse = Mathf.Max(0, -CurrentInput.Acceleration);
                            if (CurrentInput.Brake) reverse = 1.0f;
                            __instance.PitchBackwardAction2.axis = reverse;
                            __instance.PitchBackwardAction2.buttonHeld = reverse > 0.1f;
                        }
                    }
                }
            }
        }
    }

    [Serializable]
    public class AiInput
    {
        public float Steering;
        public float Acceleration;
        public bool Brake;
        public bool Reset;
    }
}

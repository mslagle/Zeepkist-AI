using System;
using System.IO;
using System.Collections.Generic;
using System.Threading.Tasks;
using Zeepkist.Ai.GtrClient;

namespace Zeepkist.Ai.Tester
{
    class Program
    {
        static void Main(string[] args)
        {
            try
            {
                RunTester().GetAwaiter().GetResult();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Critical Error: {ex}");
            }
            
            Console.WriteLine("Press any key to exit...");
        }

        static async Task RunTester()
        {
            string url = "https://cdn.zeepki.st/ghosts/01KSKV5SPZW365JM1VCFP070X0.bin";
            Console.WriteLine($"Downloading {url} directly...");
            using (var http = new System.Net.Http.HttpClient())
            {
                byte[] ghostData = await http.GetByteArrayAsync(url);
                Console.WriteLine($"Downloaded {ghostData.Length} bytes.");

                var ghostReaderFactory = new TNRD.Zeepkist.GTR.Ghosting.Readers.GhostReaderFactory();
                var reader = ghostReaderFactory.GetReader(ghostData);
                Console.WriteLine($"Got reader: {reader?.GetType().Name}");
                var ghost = reader.Read(ghostData);
                Console.WriteLine($"Parsed ghost with {ghost.FrameCount} frames!");

                var jsonFrames = new List<object>();
                for (int i = 0; i < ghost.FrameCount; i++)
                {
                    var f = ghost.GetFrame(i);
                    float speed = 0f;
                    bool arms = false, brake = false;
                    if (f is TNRD.Zeepkist.GTR.Ghosting.Ghosts.V5Ghost.Frame v5)
                    {
                        speed = v5.Speed;
                        arms = (v5.InputFlags & TNRD.Zeepkist.GTR.Ghosting.Recording.InputFlags.ArmsUp) != 0;
                        brake = (v5.InputFlags & TNRD.Zeepkist.GTR.Ghosting.Recording.InputFlags.Braking) != 0;
                    }
                    jsonFrames.Add(new {
                        p = new float[] { f.Position.x, f.Position.y, f.Position.z },
                        r = new float[] { f.Rotation.x, f.Rotation.y, f.Rotation.z, f.Rotation.w },
                        s = speed,
                        a = arms,
                        b = brake
                    });
                }

                Directory.CreateDirectory(@"M:\Code\ZeepkistAi\ghosts");
                string json = Newtonsoft.Json.JsonConvert.SerializeObject(new { LevelHash = "EZ01", Frames = jsonFrames }, Newtonsoft.Json.Formatting.Indented);
                File.WriteAllText(@"M:\Code\ZeepkistAi\ghosts\EZ01.json", json);
                
                Directory.CreateDirectory(@"M:\Code\ZeepkistAi\scripts\python\runs\EZ01");
                File.WriteAllText(@"M:\Code\ZeepkistAi\scripts\python\runs\EZ01\run_median_gtr.json", json);
                Console.WriteLine("Successfully saved ghosts/EZ01.json and runs/EZ01/run_median_gtr.json!");
            }
        }
    }
}

using System;
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
            // Console.ReadKey();
        }

        static async Task RunTester()
        {
            Console.WriteLine("Tester Starting...");
            
            GtrClient.GtrClient client = new GtrClient.GtrClient();
            string hash = "EZ02";
            
            Console.WriteLine($"Fetching best ghost for hash: {hash}");
            //int id = (int)await client.GetLevelIdByWorkshopId(3683603626);
            string url = await client.GetBestGhostUrl(hash);
            
            if (string.IsNullOrEmpty(url))
            {
                Console.WriteLine("No ghost URL found.");
                return;
            }

            Console.WriteLine($"Found Ghost URL: {url}");
            var temp = await client.DownloadAndParseGhost(url);
            
            /*
            if (points != null)
            {
                Console.WriteLine($"Successfully parsed {points.Count} points!");
                if (points.Count > 0)
                {
                    Vector3 p = points[0];
                    Console.WriteLine($"First point: x={p.x}, y={p.y}, z={p.z}");
                }
            }
            else
            {
                Console.WriteLine("Failed to parse points.");
            }*/
        }
    }
}

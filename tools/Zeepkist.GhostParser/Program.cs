using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using ProtoBuf;
using EasyCompressor;
using Newtonsoft.Json;

namespace Zeepkist.GhostParser
{
    class Program
    {
        static void Main(string[] args)
        {
            if (args.Length == 0) return;
            string filePath = args[0];
            byte[] rawData = File.ReadAllBytes(filePath);
            byte[] decompressed = new LZMACompressor().Decompress(rawData);

            Console.WriteLine("--- Testing Double (8-byte) Brute Force ---");
            for (int i = 0; i < 200; i++)
            {
                try {
                    double x = BitConverter.ToDouble(decompressed, i);
                    double y = BitConverter.ToDouble(decompressed, i + 8);
                    double z = BitConverter.ToDouble(decompressed, i + 16);
                    if (Math.Abs(x) > 10.0 && Math.Abs(x) < 5000.0)
                        Console.WriteLine($"Offset {i}: ({x}, {y}, {z})");
                } catch { }
            }

            Console.WriteLine("\n--- Testing Delta-Int (Fixed point) ---");
            for (int i = 0; i < 200; i++)
            {
                try {
                    int x = BitConverter.ToInt32(decompressed, i);
                    int y = BitConverter.ToInt32(decompressed, i + 4);
                    int z = BitConverter.ToInt32(decompressed, i + 8);
                    if (Math.Abs(x) > 1000 && Math.Abs(x) < 5000000)
                        Console.WriteLine($"Offset {i}: ({x/1000.0}, {y/1000.0}, {z/1000.0})");
                } catch { }
            }
        }
    }
}

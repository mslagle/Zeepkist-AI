// See https://aka.ms/new-console-template for more information
using Zeepkist.Ai.GtrClient;

Console.WriteLine("Hello, World!");

GtrClient client = new GtrClient();
await client.GetBestGhostUrl("ea1");
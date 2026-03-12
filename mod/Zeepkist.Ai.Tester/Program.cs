// See https://aka.ms/new-console-template for more information
using System;
using TNRD.Zeepkist.GTR.Ghosting.Recording.Data;
using Zeepkist.Ai.GtrClient;

Console.WriteLine("Hello, World!");

GtrClient client = new GtrClient();
string url = await client.GetBestGhostUrl("ea1");
var points = await client.DownloadAndParseGhost(url);
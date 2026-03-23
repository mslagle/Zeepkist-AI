using GraphQL;
using GraphQL.Client.Http;
using GraphQL.Client.Serializer.Newtonsoft;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using Zeepkist.Ai.GtrClient.Models;
using TNRD.Zeepkist.GTR.Ghosting.Readers;
using TNRD.Zeepkist.GTR.Ghosting.Ghosts;
using TNRD.Zeepkist.GTR.Ghosting.Recording;
using BepInEx.Logging;

namespace Zeepkist.Ai.GtrClient
{
    public class GtrClient
    {
        public string GtrUrl { get; set; }
        public GraphQLHttpClient GraphClient { get; set; }
        private static readonly HttpClient httpClient = new HttpClient();
        private readonly GhostReaderFactory ghostReaderFactory = new GhostReaderFactory();
        private readonly ManualLogSource logger;

        public GtrClient(ManualLogSource logger)
        {
            this.logger = logger;
            this.GtrUrl = "https://graphql.zeepki.st";
            var httpClientOptions = new GraphQLHttpClientOptions
            {
                EndPoint = new Uri(this.GtrUrl)
            };

            this.GraphClient = new GraphQLHttpClient(httpClientOptions, new NewtonsoftJsonSerializer(), httpClient);
        }

        public async Task<List<GhostFrame>> DownloadAndParseGhost(string url)
        {
            try
            {
                logger.LogInfo($"[GtrClient] Downloading ghost from {url}...");
                byte[] ghostData = await httpClient.GetByteArrayAsync(url);
                
                logger.LogInfo($"[GtrClient] Parsing ghost data ({ghostData.Length} bytes)...");
                IGhostReader reader = ghostReaderFactory.GetReader(ghostData);
                IGhost ghost = reader.Read(ghostData);
                
                if (ghost == null)
                {
                    logger.LogError("[GtrClient] Failed to parse ghost: reader.Read returned null.");
                    return null;
                }

                List<GhostFrame> frames = new List<GhostFrame>();
                for (int i = 0; i < ghost.FrameCount; i++)
                {
                    IFrame f = ghost.GetFrame(i);
                    GhostFrame frame = new GhostFrame
                    {
                        Position = f.Position,
                        Rotation = f.Rotation,
                        Speed = 0f,
                        ArmsUp = false,
                        Braking = false
                    };

                    if (f is V5Ghost.Frame v5)
                    {
                        frame.Speed = v5.Speed;
                        frame.ArmsUp = v5.InputFlags.HasFlagFast(InputFlags.ArmsUp);
                        frame.Braking = v5.InputFlags.HasFlagFast(InputFlags.Braking);
                    }
                    else
                    {
                        // Fallback for older formats
                        if (i > 0)
                        {
                            IFrame prev = ghost.GetFrame(i - 1);
                            float dt = f.Time - prev.Time;
                            if (dt > 0)
                                frame.Speed = Vector3.Distance(f.Position, prev.Position) / dt;
                        }
                    }
                    frames.Add(frame);
                }

                logger.LogInfo($"[GtrClient] Successfully parsed ghost with {frames.Count} frames.");
                return frames;
            }
            catch (Exception ex)
            {
                logger.LogError($"[GtrClient] Error downloading/parsing ghost: {ex.Message}");
                return null;
            }
        }

        public async Task<int?> GetLevelIdByWorkshopId(float workshopId)
        {
            var request = new GraphQLRequest
            {
                Query = """
                    query getLevelByWorkshop($workshopId: BigFloat!){
                      levelItems(filter: { workshopId: { equalTo: $workshopId } }) {
                        nodes {
                          levelId
                          id
                        }
                      }
                    }
                 """,
                Variables = new { workshopId = workshopId }
            };

            try
            {
                var response = await GraphClient.SendQueryAsync<GtrLevelsResponse>(request);
                if (response.Data?.Levels?.Nodes?.Count > 0)
                {
                    return response.Data.Levels.Nodes[0].Id;
                }
            }
            catch (Exception ex)
            {
                logger.LogError("[GtrClient] Error getting level ID: " + ex.Message);
            }
            return null;
        }

        public async Task<int?> GetLevelIdByHash(string hash)
        {
            var request = new GraphQLRequest
            {
                Query = """
                    query getLevelByHash($hash: String!){
                      levels(filter: { hash: { equalTo: $hash } }) {
                        nodes {
                          id
                        }
                      }
                    }
                 """,
                Variables = new { hash = hash }
            };

            try
            {
                var response = await GraphClient.SendQueryAsync<GtrLevelsResponse>(request);
                if (response.Data?.Levels?.Nodes?.Count > 0)
                {
                    return response.Data.Levels.Nodes[0].Id;
                }
            }
            catch (Exception ex)
            {
                logger.LogError("[GtrClient] Error getting level ID: " + ex.Message);
            }
            return null;
        }

        public async Task<string> GetBestGhostUrl(string hash, int checkCount = 1000)
        {
            var request = new GraphQLRequest
            {
                Query = """
                    query GetBestGhost($hash: String!, $first: Int!) {
                      levels(filter: { hash: { equalTo: $hash } }) {
                        nodes {
                          id
                          records(orderBy: TIME_ASC, first: $first) {
                            nodes {
                              recordMedia {
                                ghostUrl
                              }
                            }
                          }
                        }
                      }
                    }
                 """,
                Variables = new { hash = hash, first = checkCount }
            };

            try
            {
                var response = await GraphClient.SendQueryAsync<GtrLevelsResponse>(request);
                var nodes = response.Data?.Levels?.Nodes;
                if (nodes != null && nodes.Count > 0)
                {
                    var records = nodes[0].Records?.Nodes;
                    if (records != null && records.Count > 0)
                    {
                        // Pick a middle-ranked one as requested earlier
                        var recordsNotBlank = records.Where(x => x.RecordMedia?.GhostUrl != null).ToList();
                        int count = recordsNotBlank.Count;
                        int indexToPick = count / 2;
                        string url = recordsNotBlank[indexToPick].RecordMedia?.GhostUrl;
                        if (!string.IsNullOrEmpty(url))
                        {
                            if (url.StartsWith("//")) url = "https:" + url;
                            return url;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                logger.LogError("[GtrClient] Error getting ghost URL: " + ex.Message);
            }
            return null;
        }
    }
}

using GraphQL;
using GraphQL.Client.Http;
using GraphQL.Client.Serializer.Newtonsoft;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

namespace Zeepkist.Ai.GtrClient
{
    public class GtrClient
    {
        public string GtrUrl { get; set; }
        public GraphQLHttpClient GraphClient { get; set; } 

        public GtrClient()
        {
            this.GtrUrl = "https://graphql.zeepki.st";
            var httpClient = new HttpClient();
            httpClient.DefaultRequestHeaders.Add("User-Agent", "Zeepkist.Ai");
            httpClient.Timeout = TimeSpan.FromSeconds(10);

            var options = new GraphQLHttpClientOptions
            {
                EndPoint = new Uri(this.GtrUrl)
            };

            this.GraphClient = new GraphQLHttpClient(options, new NewtonsoftJsonSerializer(), httpClient);
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
                var response = await GraphClient.SendQueryAsync<dynamic>(request);
                if (response.Data?.levels?.nodes?.Count > 0)
                {
                    return (int)response.Data.levels.nodes[0].id;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("Error getting level ID: " + ex.Message);
            }
            return null;
        }

        public async Task<string> GetBestGhostUrl(string hash, int checkCount = 100)
        {
            var request = new GraphQLRequest
            {
                Query = """
                    query GetBestGhost($hash: String!, $first: Int!) {
                      levels(filter: { hash: { equalTo: $hash } }) {
                        nodes {
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
                Variables = new { hash = hash }
            };

            try
            {
                var response = await GraphClient.SendQueryAsync<dynamic>(request);
                var nodes = response.Data?.levels?.nodes;
                if (nodes != null && nodes.Count > 0)
                {
                    var records = nodes[0].records?.nodes;
                    if (records != null && records.Count > 0)
                    {
                        // Pick a middle-ranked one as requested earlier
                        int count = records.Count;
                        int indexToPick = count / 2;
                        string url = records[indexToPick].recordMedia?.ghostUrl;
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
                Console.WriteLine("Error getting ghost URL: " + ex.Message);
            }
            return null;
        }

        // Keep the old one for compatibility with the tester for now
        public async Task GetLevelByHash(string hash)
        {
            var id = await GetLevelIdByHash(hash);
            if (id.HasValue)
            {
                Console.WriteLine($"Found level ID: {id.Value}");
            }
            else
            {
                Console.WriteLine("Level not found.");
            }
        }
    }
}

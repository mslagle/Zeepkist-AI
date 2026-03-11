using GraphQL;
using GraphQL.Client.Http;
using GraphQL.Client.Serializer.Newtonsoft;
using System;
using System.Collections.Generic;
using System.Linq;
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
            this.GraphClient = new GraphQLHttpClient(this.GtrUrl, new NewtonsoftJsonSerializer());
        }

        public async Task GetLevelByHash(string hash)
        {
            GraphQLQuery query = new GraphQLQuery("""
                query getLevelByHash($hash: String){
                  levels(filter: { hash: { equalTo: $hash } }) {
                    nodes {
                      id
                      hash
                    }
                  }
                }
             """);

            var request = new GraphQLHttpRequest
            {
                Query = query,
                Variables = new { hash = hash }
            };

            try
            {
                var temp = await GraphClient.SendQueryAsync<dynamic>(request);
                Console.WriteLine("Sending request...", temp);
            }
            catch (Exception ex)
            {
                Console.WriteLine("Error sending request: " + ex.Message);
                return;
            }

            
        }
    }
}

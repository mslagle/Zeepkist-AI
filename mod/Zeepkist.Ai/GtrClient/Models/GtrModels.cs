using System.Collections.Generic;
using Newtonsoft.Json;

namespace Zeepkist.Ai.GtrClient.Models
{
    public class GtrLevelsResponse
    {
        [JsonProperty("levels")]
        public GtrLevelsConnection Levels { get; set; }
    }

    public class GtrLevelsConnection
    {
        [JsonProperty("nodes")]
        public List<GtrLevelNode> Nodes { get; set; }
    }

    public class GtrLevelNode
    {
        [JsonProperty("id")]
        public int Id { get; set; }

        [JsonProperty("hash")]
        public string Hash { get; set; }

        [JsonProperty("records")]
        public GtrRecordsConnection Records { get; set; }
    }

    public class GtrRecordsConnection
    {
        [JsonProperty("nodes")]
        public List<GtrRecordNode> Nodes { get; set; }
    }

    public class GtrRecordNode
    {
        [JsonProperty("id")]
        public int Id { get; set; }

        [JsonProperty("time")]
        public float Time { get; set; }

        [JsonProperty("recordMedia")]
        public GtrRecordMedia RecordMedia { get; set; }
    }

    public class GtrRecordMedia
    {
        [JsonProperty("ghostUrl")]
        public string GhostUrl { get; set; }
    }
}

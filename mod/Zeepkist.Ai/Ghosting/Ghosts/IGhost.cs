using System.Collections.Generic;
using TNRD.Zeepkist.GTR.Ghosting.Playback;
using UnityEngine;

namespace TNRD.Zeepkist.GTR.Ghosting.Ghosts;

public interface IGhost
{
    Color Color { get; }
    int FrameCount { get; }
    void Initialize(GhostData ghost);
    void ApplyCosmetics(string steamName);
    void Start();
    void Stop();
    void Update();
    void FixedUpdate();
    List<Vector3> GetPositions();
    IFrame GetFrame(int index);
}

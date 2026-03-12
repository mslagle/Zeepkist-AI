using System;
using TNRD.Zeepkist.GTR.Ghosting.Ghosts;

namespace TNRD.Zeepkist.GTR.Ghosting.Readers;

public abstract class GhostReaderBase<TGhost> : IGhostReader where TGhost : IGhost
{
    public abstract IGhost Read(byte[] data);
}

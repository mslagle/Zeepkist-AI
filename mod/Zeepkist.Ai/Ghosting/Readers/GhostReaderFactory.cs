using System;
using System.IO;
using System.IO.Compression;
using EasyCompressor;
using TNRD.Zeepkist.GTR.Ghosting.Readers;

namespace TNRD.Zeepkist.GTR.Ghosting.Readers;

public class GhostReaderFactory
{
    public IGhostReader GetReader(byte[] buffer)
    {
        int version = GetVersion(buffer);

        switch (version)
        {
            case 1:
                return new V1Reader();
            case 2:
                return new V2Reader();
            case 3:
                return new V3Reader();
            case 4:
                return new V4Reader();
            case 5:
                return new V5Reader();
            default:
                throw new NotSupportedException($"Version {version} is not supported.");
        }
    }

    private int GetVersion(byte[] buffer)
    {
        if (IsLZMA(buffer, out _))
        {
            return 5;
        }

        if (IsGZipped(buffer, out byte[] decompressed))
        {
            using BinaryReader reader = new(new MemoryStream(decompressed));
            return reader.ReadInt32();
        }
        else
        {
            using MemoryStream stream = new(buffer);
            using BinaryReader reader = new(stream);
            return reader.ReadInt32();
        }
    }

    private static bool IsLZMA(byte[] buffer, out byte[] decompressed)
    {
        try
        {
            decompressed = LZMACompressor.Shared.Decompress(buffer);
            return true;
        }
        catch
        {
            decompressed = null;
            return false;
        }
    }

    private static bool IsGZipped(byte[] buffer, out byte[] decompressed)
    {
        try
        {
            decompressed = GZipCompressor.Shared.Decompress(buffer);
            return true;
        }
        catch
        {
            decompressed = null;
            return false;
        }
    }
}

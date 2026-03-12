using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using TNRD.Zeepkist.GTR.Ghosting.Ghosts;
using UnityEngine;

namespace TNRD.Zeepkist.GTR.Ghosting.Readers;

public class V4Reader : GhostReaderBase<V4Ghost>
{
    public override IGhost Read(byte[] data)
    {
        List<V4Ghost.Frame> frames = new();
        ulong steamId;
        int soapboxId;
        int hatId;
        int colorId;

        using MemoryStream ms = new(data);
        GZipStream zip = null;
        BinaryReader reader = null;

        if (IsGZipped(data))
        {
            zip = new GZipStream(ms, CompressionMode.Decompress);
            reader = new BinaryReader(zip);
        }
        else
        {
            reader = new BinaryReader(ms);
        }

        try
        {
            reader.ReadInt32();
            steamId = reader.ReadUInt64();
            soapboxId = reader.ReadInt32();
            hatId = reader.ReadInt32();
            colorId = reader.ReadInt32();
            byte precision = reader.ReadByte();
            int frameCount = reader.ReadInt32();

            Vector3 currentPosition = Vector3.zero;

            for (int i = 0; i < frameCount; i++)
            {
                if (i % precision == 0 || i == frameCount - 1)
                {
                    ResetFrame resetFrame = ResetFrame.Read(reader);
                    currentPosition = new Vector3(resetFrame.PositionX, resetFrame.PositionY, resetFrame.PositionZ);
                    
                    frames.Add(new V4Ghost.Frame(
                        resetFrame.Time,
                        currentPosition,
                        new Quaternion(
                            ShortToFloat(resetFrame.RotationX),
                            ShortToFloat(resetFrame.RotationY),
                            ShortToFloat(resetFrame.RotationZ),
                            ShortToFloat(resetFrame.RotationW)),
                        resetFrame.Steering,
                        resetFrame.Flags.HasFlag(Flags.ArmsUp),
                        resetFrame.Flags.HasFlag(Flags.IsBraking)));
                }
                else
                {
                    DeltaFrame deltaFrame = DeltaFrame.Read(reader);
                    currentPosition += new Vector3(
                        ShortToFloat(deltaFrame.PositionX),
                        ShortToFloat(deltaFrame.PositionY),
                        ShortToFloat(deltaFrame.PositionZ));

                    frames.Add(new V4Ghost.Frame(
                        deltaFrame.Time,
                        currentPosition,
                        new Quaternion(
                            ShortToFloat(deltaFrame.RotationX, 30000),
                            ShortToFloat(deltaFrame.RotationY, 30000),
                            ShortToFloat(deltaFrame.RotationZ, 30000),
                            ShortToFloat(deltaFrame.RotationW, 30000)),
                        deltaFrame.Steering,
                        deltaFrame.Flags.HasFlag(Flags.ArmsUp),
                        deltaFrame.Flags.HasFlag(Flags.IsBraking)));
                }
            }
        }
        finally
        {
            reader.Dispose();
            zip?.Dispose();
        }

        return new V4Ghost(steamId, soapboxId, hatId, colorId, frames);
    }

    private static bool IsGZipped(byte[] buffer)
    {
        return buffer[0] == 0x1f && buffer[1] == 0x8b;
    }

    private static float ShortToFloat(short value, float scale = 10000f)
    {
        return value / scale;
    }

    public abstract class GhostFrame
    {
        public float Time;
    }

    public class DeltaFrame : GhostFrame
    {
        public short PositionX;
        public short PositionY;
        public short PositionZ;
        public short RotationX;
        public short RotationY;
        public short RotationZ;
        public short RotationW;
        public byte Steering;
        public Flags Flags;

        public static DeltaFrame Read(BinaryReader reader)
        {
            DeltaFrame f = new()
            {
                Time = reader.ReadSingle(),
                PositionX = reader.ReadInt16(),
                PositionY = reader.ReadInt16(),
                PositionZ = reader.ReadInt16(),
                RotationX = reader.ReadInt16(),
                RotationY = reader.ReadInt16(),
                RotationZ = reader.ReadInt16(),
                RotationW = reader.ReadInt16(),
                Steering = reader.ReadByte(),
                Flags = (Flags)reader.ReadByte()
            };
            return f;
        }
    }

    public class ResetFrame : GhostFrame
    {
        public float PositionX;
        public float PositionY;
        public float PositionZ;
        public short RotationX;
        public short RotationY;
        public short RotationZ;
        public short RotationW;
        public byte Steering;
        public Flags Flags;

        public static ResetFrame Read(BinaryReader reader)
        {
            ResetFrame f = new();
            f.Time = reader.ReadSingle();
            f.PositionX = reader.ReadSingle();
            f.PositionY = reader.ReadSingle();
            f.PositionZ = reader.ReadSingle();
            f.RotationX = reader.ReadInt16();
            f.RotationY = reader.ReadInt16();
            f.RotationZ = reader.ReadInt16();
            f.RotationW = reader.ReadInt16();
            f.Steering = reader.ReadByte();
            f.Flags = (Flags)reader.ReadByte();
            return f;
        }
    }

    [Flags]
    public enum Flags : byte
    {
        None = 0,
        ArmsUp = 1 << 0,
        IsBraking = 1 << 1,
    }
}

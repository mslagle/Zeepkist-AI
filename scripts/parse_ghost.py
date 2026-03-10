import struct
import io
import os

try:
    import pylzma
    HAS_PYLZMA = True
except ImportError:
    HAS_PYLZMA = False

class ZeepGhostParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.header = {}
        self.frames = []

    def parse(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Ghost file not found: {self.file_path}")

        with open(self.file_path, 'rb') as f:
            raw_data = f.read()

        # Zeepkist GTR Ghost files usually start with LZMA (5D 00 00 01 00)
        # 5 bytes properties, 8 bytes uncompressed size
        if raw_data.startswith(b'\x5d\x00\x00'):
            if not HAS_PYLZMA:
                print("WARNING: pylzma not found, attempting direct parse (will likely fail)")
                reader = io.BytesIO(raw_data)
            else:
                try:
                    # pylzma.decompress expects the full 13-byte header
                    decompressed = pylzma.decompress(raw_data)
                    reader = io.BytesIO(decompressed)
                except Exception as e:
                    print(f"LZMA Decompression failed: {e}. Trying direct.")
                    reader = io.BytesIO(raw_data)
        else:
            reader = io.BytesIO(raw_data)

        # Frame structure: Vector3(3 floats) + Quaternion(4 floats) = 7 floats = 28 bytes
        # Some versions might have 8 floats (including time)
        
        data = reader.read()
        total_bytes = len(data)
        
        # We try to guess frame size based on common lengths
        # 28 bytes = pos(12) + rot(16)
        # 32 bytes = time(4) + pos(12) + rot(16)
        
        for frame_size in [28, 32]:
            if total_bytes % frame_size == 0:
                print(f"Detected potential frame size: {frame_size} bytes")
                reader.seek(0)
                self.frames = []
                try:
                    while True:
                        buf = reader.read(frame_size)
                        if len(buf) < frame_size: break
                        
                        if frame_size == 28:
                            # pos(x,y,z), rot(x,y,z,w)
                            f = struct.unpack('<fffffff', buf)
                            self.frames.append({'pos': f[0:3], 'rot': f[3:7]})
                        else:
                            # time, pos(x,y,z), rot(x,y,z,w)
                            f = struct.unpack('<ffffffff', buf)
                            self.frames.append({'pos': f[1:4], 'rot': f[4:8]})
                    
                    if len(self.frames) > 10:
                        print(f"Successfully parsed {len(self.frames)} frames.")
                        return self.header, self.frames
                except:
                    continue

        # If division didn't work, maybe there is a small header?
        # Let's try skipping first few bytes (e.g. version int)
        for offset in range(1, 16):
            remaining = total_bytes - offset
            for frame_size in [28, 32]:
                if remaining > 0 and remaining % frame_size == 0:
                    print(f"Found match at offset {offset} with frame size {frame_size}")
                    reader.seek(offset)
                    self.frames = []
                    try:
                        while True:
                            buf = reader.read(frame_size)
                            if len(buf) < frame_size: break
                            if frame_size == 28:
                                f = struct.unpack('<fffffff', buf)
                                self.frames.append({'pos': f[0:3], 'rot': f[3:7]})
                            else:
                                f = struct.unpack('<ffffffff', buf)
                                self.frames.append({'pos': f[1:4], 'rot': f[4:8]})
                        return self.header, self.frames
                    except:
                        continue

        # Last resort: just try to read as many 28-byte chunks as possible
        print("Last resort: reading 28-byte chunks until failure")
        reader.seek(0)
        self.frames = []
        while True:
            buf = reader.read(28)
            if len(buf) < 28: break
            try:
                f = struct.unpack('<fffffff', buf)
                self.frames.append({'pos': f[0:3], 'rot': f[3:7]})
            except:
                break
        
        return self.header, self.frames

if __name__ == "__main__":
    pass

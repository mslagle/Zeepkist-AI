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

        # Check for LZMA signature (5D 00 00 ...)
        if raw_data.startswith(b'\x5d\x00\x00'):
            if not HAS_PYLZMA:
                raise ImportError("Ghost file is compressed with LZMA. Please install 'pylzma' via pip.")
            
            print(f"Decompressing LZMA ghost: {self.file_path}")
            try:
                # LZMA format: 5 bytes properties, 8 bytes uncompressed size, then data
                # We use pylzma.decompress which handles the stream
                decompressed = pylzma.decompress(raw_data)
                reader = io.BytesIO(decompressed)
            except Exception as e:
                print(f"LZMA Decompression failed: {e}")
                # Fallback to direct read if it was a false positive signature
                reader = io.BytesIO(raw_data)
        else:
            reader = io.BytesIO(raw_data)

        try:
            # 1. Version (int32)
            self.header['version'] = struct.unpack('<i', reader.read(4))[0]
            
            # 2. Steam ID (int64)
            self.header['steam_id'] = struct.unpack('<q', reader.read(8))[0]

            # 3. Username (C# string)
            self.header['username'] = self._read_csharp_string(reader)

            # 4. Total Time (float32)
            self.header['total_time'] = struct.unpack('<f', reader.read(4))[0]

            # 5. Level Hash (C# string)
            self.header['level_hash'] = self._read_csharp_string(reader)

            # 6. Frame Count (int32)
            frame_count = struct.unpack('<i', reader.read(4))[0]
            self.header['frame_count'] = frame_count

            # 7. Frames
            for _ in range(frame_count):
                # Position (3x float32)
                px, py, pz = struct.unpack('<fff', reader.read(12))
                # Rotation (4x float32)
                rx, ry, rz, rw = struct.unpack('<ffff', reader.read(16))
                
                self.frames.append({
                    'pos': (px, py, pz),
                    'rot': (rx, ry, rz, rw)
                })

        except (struct.error, EOFError) as e:
            print(f"Ghost parsing interrupted (possible version mismatch or corrupt file): {e}")
            if not self.frames:
                raise e

        return self.header, self.frames

    def _read_csharp_string(self, reader):
        # Read 7-bit encoded integer (length)
        length = 0
        shift = 0
        while True:
            b = reader.read(1)
            if not b:
                raise EOFError("Unexpected end of stream while reading string length")
            byte = struct.unpack('<B', b)[0]
            length |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        
        if length == 0:
            return ""
            
        data = reader.read(length)
        return data.decode('utf-8', errors='ignore')

if __name__ == "__main__":
    # Test
    # parser = ZeepGhostParser("ghosts/ea1.zeepghost")
    # h, f = parser.parse()
    # print(f"Parsed {len(f)} frames")
    pass

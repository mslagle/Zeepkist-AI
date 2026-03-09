import struct
import io

class ZeepGhostParser:
    def __init__(self, file_path):
        self.file_path = file_path
        self.header = {}
        self.frames = []

    def parse(self):
        with open(self.file_path, 'rb') as f:
            data = f.read()
            reader = io.BytesIO(data)

            # 1. Version (int32)
            self.header['version'] = struct.unpack('<i', reader.read(4))[0]
            
            # 2. Steam ID (int64)
            self.header['steam_id'] = struct.unpack('<q', reader.read(8))[0]

            # 3. Username (length-prefixed string)
            username_len = struct.unpack('<B', reader.read(1))[0] # Assuming small string, but C# uses 7-bit encoded int
            # Re-evaluating: C# BinaryReader.ReadString() uses 7-bit encoded int for length.
            # For simplicity, if we know the game uses a specific string format:
            reader.seek(-1, io.SEEK_CUR)
            username = self._read_csharp_string(reader)
            self.header['username'] = username

            # 4. Total Time (float32)
            self.header['total_time'] = struct.unpack('<f', reader.read(4))[0]

            # 5. Level Hash (string)
            self.header['level_hash'] = self._read_csharp_string(reader)

            # 6. Frame Count (int32)
            frame_count = struct.unpack('<i', reader.read(4))[0]
            self.header['frame_count'] = frame_count

            for _ in range(frame_count):
                frame = {}
                # Position (3x float32)
                px, py, pz = struct.unpack('<fff', reader.read(12))
                frame['pos'] = (px, py, pz)
                
                # Rotation (4x float32)
                rx, ry, rz, rw = struct.unpack('<ffff', reader.read(16))
                frame['rot'] = (rx, ry, rz, rw)
                
                # Depending on version, there might be more (velocity, etc.)
                # If we hit EOF, we stop.
                self.frames.append(frame)

        return self.header, self.frames

    def _read_csharp_string(self, reader):
        # Read 7-bit encoded integer (length)
        length = 0
        shift = 0
        while True:
            byte = struct.unpack('<B', reader.read(1))[0]
            length |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7
        
        return reader.read(length).decode('utf-8')

if __name__ == "__main__":
    # Example usage (requires a real .zeepghost file)
    # parser = ZeepGhostParser("example.zeepghost")
    # header, frames = parser.parse()
    # print(f"Parsed {len(frames)} frames for {header['username']}")
    pass

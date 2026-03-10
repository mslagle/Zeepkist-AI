import struct
import io
import os
import lzma

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

        # 1. Decompress LZMA
        if raw_data.startswith(b'\x5d\x00\x00'):
            try:
                data = lzma.decompress(raw_data, format=lzma.FORMAT_ALONE)
            except Exception as e:
                print(f"LZMA Decompression failed: {e}")
                # Fallback to raw if possible
                data = raw_data
        else:
            data = raw_data

        # 2. Parse Protobuf-like stream
        # Each frame is a message containing Position (Tag 2) and Rotation (Tag 3)
        # Position is 3x fixed32 (15 bytes delimited)
        # Rotation is 4x fixed32 (20 bytes delimited)
        
        self.frames = []
        i = 0
        total = len(data)
        
        while i < total - 40:
            # We look for the start of a frame. 
            # In our observed data, Position is often Tag 2 (0x12) or Tag 1 (0x0A)
            # and follows a specific length.
            
            # Let's search for the Vector3 pattern: 0D [4] 15 [4] 1D [4]
            # This is Tag 1, 2, 3 of a nested message
            
            found_pos = False
            if i + 15 < total and data[i] == 0x0D and data[i+5] == 0x15 and data[i+10] == 0x1D:
                # Potential Vector3 (raw or inside message)
                try:
                    px, py, pz = struct.unpack('<fff', data[i+1:i+5] + data[i+6:i+10] + data[i+11:i+15])
                    
                    # Now look for Rotation nearby (Tag 3 usually follows)
                    # We scan a small window for the Quaternion pattern: 0D [4] 15 [4] 1D [4] 25 [4]
                    for j in range(i + 15, min(i + 60, total - 20)):
                        if data[j] == 0x0D and data[j+5] == 0x15 and data[j+10] == 0x1D and data[j+15] == 0x25:
                            rx, ry, rz, rw = struct.unpack('<ffff', data[j+1:j+5] + data[j+6:j+10] + data[j+11:j+15] + data[j+16:j+20])
                            self.frames.append({
                                'pos': (float(px), float(py), float(pz)),
                                'rot': (float(rx), float(ry), float(rz), float(rw))
                            })
                            i = j + 20 # Advance to end of rotation
                            found_pos = True
                            break
                except:
                    pass
            
            if not found_pos:
                i += 1

        if not self.frames:
            print("WARNING: Protobuf parser found no frames. Falling back to raw float scan.")
            return self._fallback_parse(data)

        print(f"Successfully parsed {len(self.frames)} frames via Protobuf scanner.")
        return self.header, self.frames

    def _fallback_parse(self, data):
        # Last resort: just find any sequence of 7 or 8 floats that look like a car
        self.frames = []
        i = 0
        while i < len(data) - 32:
            try:
                # Try 32-byte frame
                f = struct.unpack('<ffffffff', data[i:i+32])
                if -2000 < f[1] < 5000 and -2000 < f[2] < 5000 and -2000 < f[3] < 5000:
                    self.frames.append({'pos': f[1:4], 'rot': f[4:8]})
                    i += 32
                    continue
            except: pass
            i += 1
        return self.header, self.frames

if __name__ == "__main__":
    pass

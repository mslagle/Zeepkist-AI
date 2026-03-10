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
                data = raw_data
        else:
            data = raw_data

        # 2. Parse Protobuf
        # The structure observed in hex:
        # 0A [length] -> Start of Frame message
        #   Inside frame:
        #   0D [4 bytes] -> Position X (Tag 1, fixed32)
        #   15 [4 bytes] -> Position Y (Tag 2, fixed32)
        #   1D [4 bytes] -> Position Z (Tag 3, fixed32)
        #   ... then rotation tags 4, 5, 6, 7
        
        self.frames = []
        i = 0
        total = len(data)
        
        while i < total - 30:
            # Look for Vector3 pattern: 0D [4] 15 [4] 1D [4]
            # This is extremely reliable for finding floats in protobuf-net
            if data[i] == 0x0D and data[i+5] == 0x15 and data[i+10] == 0x1D:
                try:
                    px, py, pz = struct.unpack('<fff', data[i+1:i+5] + data[i+6:i+10] + data[i+11:i+15])
                    
                    # Rotations follow (Tags 4, 5, 6, 7 -> 0x25, 0x2D, 0x35, 0x3D)
                    # We look ahead slightly for these
                    rx, ry, rz, rw = 0, 0, 0, 1
                    found_rot = False
                    for j in range(i + 15, i + 50):
                        if j + 20 <= total:
                            if data[j] == 0x25 and data[j+5] == 0x2D and data[j+10] == 0x35 and data[j+15] == 0x3D:
                                rx, ry, rz, rw = struct.unpack('<ffff', data[j+1:j+5] + data[j+6:j+10] + data[j+11:j+15] + data[j+16:j+20])
                                found_rot = True
                                i = j + 20
                                break
                    
                    # Only add if coordinates are somewhat reasonable (not near zero or infinite)
                    if any(abs(v) > 0.001 for v in [px, py, pz]) and all(abs(v) < 100000 for v in [px, py, pz]):
                        self.frames.append({
                            'pos': (float(px), float(py), float(pz)),
                            'rot': (float(rx), float(ry), float(rz), float(rw))
                        })
                        if not found_rot: i += 15
                except:
                    i += 1
            else:
                i += 1

        if not self.frames:
            print("WARNING: Protobuf parser found no valid frames. Falling back to raw float scan.")
            return self._fallback_parse(data)

        print(f"Successfully parsed {len(self.frames)} frames via Protobuf scanner.")
        return self.header, self.frames

    def _fallback_parse(self, data):
        self.frames = []
        i = 0
        while i < len(data) - 28:
            try:
                # Try raw 7-float sequence
                f = struct.unpack('<fffffff', data[i:i+28])
                if all(abs(v) < 5000 for v in f[0:3]) and any(abs(v) > 1 for v in f[0:3]):
                    self.frames.append({'pos': f[0:3], 'rot': f[3:7]})
                    i += 28
                    continue
            except: pass
            i += 1
        return self.header, self.frames

if __name__ == "__main__":
    pass

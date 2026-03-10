import struct
import io
import os
import lzma
import gzip
import numpy as np

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

        # 1. Detect and Decompress
        data = None
        # Try LZMA (Zeepkist standard)
        if raw_data.startswith(b'\x5d\x00\x00'):
            try:
                data = lzma.decompress(raw_data, format=lzma.FORMAT_ALONE)
                print(f"Decompressed LZMA: {len(data)} bytes")
            except: pass
        
        # Try GZIP (Fallback based on GhostReaderFactory)
        if data is None and raw_data.startswith(b'\x1f\x8b'):
            try:
                data = gzip.decompress(raw_data)
                print(f"Decompressed GZIP: {len(data)} bytes")
            except: pass
            
        # Fallback to raw if no compression detected or decompression failed
        if data is None:
            data = raw_data
            print(f"Using raw data: {len(data)} bytes")

        # 2. Advanced Brute-Force Telemetry Scanner
        # We search for ANY sequence of 7 or 8 floats that look like a car.
        # This bypasses all Protobuf tags and metadata reliably.
        
        self.frames = []
        total = len(data)
        
        # Scan every single byte offset for maximum reliability
        print("Brute-forcing float sequences...")
        
        i = 0
        while i < total - 32:
            try:
                # Try 32-byte (Time, Pos, Rot)
                f8 = struct.unpack('<ffffffff', data[i:i+32])
                # Heuristics:
                # 1. Normalized rotation (indices 4-8)
                # 2. Reasonable coordinates (indices 1-4)
                # 3. Small positive time (index 0)
                if (0 <= f8[0] < 3600 and 
                    all(-5000 < x < 5000 for x in f8[1:4]) and 
                    0.99 < (f8[4]**2 + f8[5]**2 + f8[6]**2 + f8[7]**2) < 1.01):
                    
                    self.frames.append({'pos': f8[1:4], 'rot': f8[4:8]})
                    i += 32 
                    continue

                # Try 28-byte (Pos, Rot)
                f7 = struct.unpack('<fffffff', data[i:i+28])
                if (all(-5000 < x < 5000 for x in f7[0:3]) and 
                    0.99 < (f7[3]**2 + f7[4]**2 + f7[5]**2 + f7[6]**2) < 1.01):
                    
                    self.frames.append({'pos': f7[0:3], 'rot': f7[3:7]})
                    i += 28
                    continue
            except: pass
            i += 1

        # Deduplicate results from overlapping windows
        if self.frames:
            unique = []
            unique.append(self.frames[0])
            for f in self.frames[1:]:
                # Only add if car has moved significantly or rotation changed
                dist = np.linalg.norm(np.array(f['pos']) - np.array(unique[-1]['pos']))
                if dist > 0.01:
                    unique.append(f)
            self.frames = unique

        print(f"Successfully parsed {len(self.frames)} frames.")
        return self.header, self.frames

if __name__ == "__main__":
    import sys
    test_file = "ghosts/ea1.zeepghost"
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
    
    if os.path.exists(test_file):
        print(f"Testing parser on {test_file}...")
        parser = ZeepGhostParser(test_file)
        h, f = parser.parse()
        if f:
            print(f"First frame pos: {f[0]['pos']}")
            print(f"Last frame pos: {f[-1]['pos']}")
        else:
            print("Failed to extract frames.")

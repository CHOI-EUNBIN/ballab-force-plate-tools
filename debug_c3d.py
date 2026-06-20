"""
Debug script to inspect C3D file structure
"""
import sys
sys.path.insert(0, '.')

from core.c3d_reader import print_c3d_info
import glob

# Find all C3D files in the current directory and subdirectories
c3d_files = glob.glob("**/*.c3d", recursive=True)

if not c3d_files:
    print("No C3D files found in the current directory or subdirectories")
    print("Please provide a C3D file path")
else:
    for c3d_file in c3d_files[:5]:  # First 5 files
        print_c3d_info(c3d_file)

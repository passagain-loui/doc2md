import shutil
import os

def clean_cache():
    cache_dirs = ['__pycache__', 'build', 'dist', '.cache']
    for cache_dir in cache_dirs:
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)

clean_cache()
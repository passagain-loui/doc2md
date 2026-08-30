import subprocess

def build_release():
    subprocess.run(['python', 'build_exe.py'])
    subprocess.run(['python', 'build_installer.py'])

build_release()
import subprocess
import json
import sys

def execute_function(image, event):
    event_json = json.dumps(event)
    cmd = f'docker run --rm {image} python function.py \'{event_json}\''
    try:
        output = subprocess.check_output(cmd, shell=True, timeout=5)
        return json.loads(output)
    except subprocess.TimeoutExpired:
        return {"error": "Function timed out"}
    except subprocess.CalledProcessError as e:
        return {"error": str(e)}

if __name__ == "__main__":
    event = {"input": "test"}
    print(execute_function("my-python-base", event))
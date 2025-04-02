def handler(event):
    return {"message": "Hello, world!", "event": event}

if __name__ == "__main__":
    import json, sys
    event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(handler(event)))
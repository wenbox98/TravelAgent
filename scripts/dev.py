import argparse
from _bootstrap import enter


def main():
    enter()
    import uvicorn
    from travel_agent.main import create_app
    from travel_agent.settings import RuntimePaths, Settings
    from travel_agent.persistence.database import Database
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock"], default="mock")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    settings = Settings.load(mode=args.mode, preferred_port=args.port)
    paths = RuntimePaths.default()
    paths.ensure()
    # Migrate before serving; failure stops startup rather than serving a broken DB.
    with Database(paths.database):
        pass
    print("合成演示：未连接小红书、模型、地图或报价服务。", flush=True)
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.preferred_port, access_log=False)


if __name__ == "__main__":
    main()

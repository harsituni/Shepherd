"""Live builder: fetch forecast weather and write one Contract A to runs/{run_id}/scenario.json.

    python -m backend.sim.weatherpipe.build backend/sim/scenarios/edm-demo-1.json \
        --source openweather:forecast-3h [--t0 ...] --out runs/ [--run-engine]

Needs OPENWEATHER_API_KEY for openweather: sources. cache:/canned: sources work offline.
"""

import argparse
from pathlib import Path

from backend.sim.weatherpipe.conventions import bbox_centroid, default_t0, parse_utc
from backend.sim.weatherpipe.resample import build_weather_series, coverage_metadata
from backend.sim.weatherpipe.scenario import build_scenario, load_config, next_run_id, write_scenario
from backend.sim.weatherpipe.sources import DEFAULT_CACHE_DIR, fetch_weather


def build_live(config_path, source, t0, runs_dir, cache_dir=DEFAULT_CACHE_DIR, session=None) -> Path:
    config = load_config(config_path)
    lat, lon = bbox_centroid(config.bbox)
    obs, weather_source = fetch_weather(
        lat, lon, source or config.weather_default_source, t0=t0, cache_dir=cache_dir, session=session
    )
    weather = build_weather_series(obs, t0, config.horizon_min)
    weather_source.update(coverage_metadata(obs, t0, config.horizon_min))
    run_id = next_run_id(config.scenario_id, runs_dir)
    scenario = build_scenario(config, weather, t0, run_id, weather_source)
    return write_scenario(scenario, Path(runs_dir) / run_id / "scenario.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a Contract A scenario from forecast weather.")
    parser.add_argument("config", type=Path)
    parser.add_argument("--source", help="openweather:forecast-3h | openweather:onecall-hourly | "
                                         "cache:<path> | canned:<path> (default: the config's)")
    parser.add_argument("--t0", help="ISO 8601 UTC, default now rounded down to the hour")
    parser.add_argument("--out", type=Path, default=Path("runs"))
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--run-engine", action="store_true", help="also run the spread engine")
    args = parser.parse_args(argv)

    t0 = parse_utc(args.t0) if args.t0 else default_t0()
    path = build_live(args.config, args.source, t0, args.out, args.cache_dir)
    print(f"wrote {path}")
    if args.run_engine:
        from backend.sim.engine.run import run_engine
        result = run_engine(path, args.out)
        print(f"engine {result['run_id']}: {result['out_dir']} ({result['elapsed_s']} s)")


if __name__ == "__main__":
    main()
